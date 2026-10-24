"""Vietnamese static reports from recorded data; no solver is run during rendering."""

import json
import os
import statistics
import tempfile
from collections import Counter, defaultdict
from pathlib import Path

os.environ.setdefault("MPLCONFIGDIR", str(Path(tempfile.gettempdir()) / "bloxorz-matplotlib"))

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch, Rectangle

from bloxorz_solver.benchmark.experiments import axis_label, report_view
from bloxorz_solver.benchmark.runner import read_manifest

FAMILIES = {
    "ordinary": "Ô thường",
    "fragile": "Ô dễ vỡ",
    "switch": "Công tắc và cầu",
    "split": "Tách khối",
    "unsolvable": "Vô nghiệm",
}
TOPOLOGIES = {"walk": "Khắc đường đi", "rooms": "Phòng và hành lang", "random": "Ngẫu nhiên"}
STATUS = {
    "solved": "Giải được",
    "exhausted": "Vô nghiệm",
    "timeout": "Hết thời gian",
    "memory_limit": "Vượt bộ nhớ",
    "invalid_path": "Đường đi sai",
    "error": "Lỗi",
}


def summarize(rows, records, solvers):
    positive = {
        r["id"] for r in records if r["certificate"]["status"] in ("solved", "optimal", "witness")
    }
    groups = defaultdict(list)
    memory = {}
    for row in rows:
        if row["mode"] == "timing":
            groups[row["solver"], row["id"]].append(row)
        elif row["status"] == "solved":
            memory[row["solver"], row["id"]] = row.get("peak_memory")
    solved = {
        s: {
            i
            for (algo, i), runs in groups.items()
            if algo == s and i in positive and all(r["status"] == "solved" for r in runs)
        }
        for s in solvers
    }
    common = set.intersection(*(solved[s] for s in solvers)) if solvers else set()
    per_map = {}
    for (solver, identity), runs in groups.items():
        if identity in solved[solver]:
            per_map[solver, identity] = {
                metric: statistics.median(values)
                if (values := [r.get(metric) for r in runs if r.get(metric) is not None])
                else None
                for metric in (
                    "search_time",
                    "expanded_nodes",
                    "length_ratio",
                    "initialization_time",
                    "total_time",
                )
            }
    return positive, groups, solved, common, per_map, memory


def create_report(corpus: Path, results: Path, output: Path):
    manifest = read_manifest(corpus)
    metadata = json.loads((results / "metadata.json").read_text())
    if metadata["corpus_hash"] != manifest["corpus_hash"]:
        raise ValueError("Results belong to a different corpus")
    rows = [json.loads(line) for line in (results / "runs.jsonl").read_text().splitlines()]
    selected = set(metadata["selected_ids"])
    metadata, rows, names = report_view(metadata, rows)
    solvers = metadata["solvers"]
    time_metric = "total_time" if metadata.get("measurement_scope") else "search_time"
    colors = {s: plt.get_cmap("tab10")(i % 10) for i, s in enumerate(solvers)}
    records = [r for r in manifest["records"] if r["id"] in selected]
    seen = set()
    for row in rows:
        key = (row["id"], row["solver"], row["mode"], row["repetition"])
        if key in seen or row["id"] not in selected or row["solver"] not in solvers:
            raise ValueError("Duplicate or unexpected experiment row")
        seen.add(key)
    expected = {
        (i, s, "timing", rep)
        for i in selected
        for s in solvers
        for rep in range(metadata["repeats"])
    }
    expected |= {(i, s, "memory", 0) for i in selected for s in solvers}
    if seen != expected:
        raise ValueError("Incomplete experiment; refusing a misleading report")
    output.mkdir(parents=True, exist_ok=True)
    plt.rcParams.update(
        {
            "font.family": "DejaVu Sans",
            "font.size": 10,
            "axes.titleweight": "bold",
            "axes.labelcolor": "#243746",
            "text.color": "#243746",
            "axes.spines.top": False,
            "axes.spines.right": False,
            "axes.edgecolor": "#B7C6CE",
            "figure.facecolor": "#F7FAFC",
            "axes.facecolor": "white",
            "savefig.facecolor": "#F7FAFC",
            "svg.hashsalt": "bloxorz-v1",
        }
    )
    images = []

    def save(fig, filename, title):
        fig.savefig(output / f"{filename}.svg", bbox_inches="tight", metadata={"Date": None})
        fig.savefig(output / f"{filename}.png", dpi=300, bbox_inches="tight")
        plt.close(fig)
        images.append((filename, title))

    positive, groups, solved, common, per_map, memory = summarize(rows, records, solvers)
    timing = [r for r in rows if r["mode"] == "timing"]
    failures = sum(
        r["status"] in ("timeout", "memory_limit", "error", "invalid_path") for r in timing
    )
    fig, ax = plt.subplots(figsize=(12, 3.5))
    ax.axis("off")
    ax.text(0, 1, "BLOXORZ  /  BÁO CÁO THỰC NGHIỆM", fontsize=11, color="#607D8B")
    ax.text(0, 0.77, "Toàn cảnh kết quả benchmark", fontsize=24, weight="bold")
    cards = [
        (str(len(records)), "Màn được đo"),
        (str(len(positive)), "Màn có lời giải"),
        (str(len(timing)), "Lượt đo thời gian"),
        (str(failures), "Lượt lỗi / chạm giới hạn"),
    ]
    for index, (value, label) in enumerate(cards):
        x = index * 0.25
        ax.text(x, 0.38, value, fontsize=30, weight="bold", color="#0072B2")
        ax.text(x, 0.18, label, fontsize=10)
    ax.text(
        0,
        -0.05,
        f"Chi phí đơn vị • {metadata['repeats']} lượt / thuật toán / màn • "
        f"Giới hạn {metadata['timeout']:g} giây • {metadata['memory_mib']} MiB",
    )
    save(fig, "01-tong-quan", "Toàn cảnh kết quả benchmark")

    fig, ax = plt.subplots(figsize=(10, 5))
    for si, solver in enumerate(solvers):
        times = sorted(per_map[solver, i][time_metric] for i in solved[solver])
        xs = [0, *times, metadata["timeout"]]
        ys = [
            0,
            *[100 * (i + 1) / max(1, len(positive)) for i in range(len(times))],
            100 * len(times) / max(1, len(positive)),
        ]
        ax.step(
            xs,
            ys,
            where="post",
            label=names[solver],
            color=colors[solver],
            linestyle=["-", "--", "-.", ":"][si % 4],
            linewidth=2,
        )
    ax.set(
        xlabel="Tổng thời gian trung vị (giây)"
        if time_metric == "total_time"
        else "Thời gian tìm kiếm trung vị (giây)",
        ylabel="Tỷ lệ màn giải được (%)",
        title="Tỷ lệ giải được theo thời gian",
        ylim=(0, 102),
    )
    ax.set_xscale("symlog", linthresh=0.001)
    ax.set_xlim(0, metadata["timeout"])
    ax.grid(alpha=0.2)
    ax.legend()
    fig.text(
        0.12,
        -0.01,
        "Mẫu số gồm mọi màn có lời giải tham chiếu; chỉ tính màn thành công ở mọi lượt.",
        fontsize=9,
    )
    save(fig, "02-ty-le-giai", "Tỷ lệ giải được theo thời gian")

    fig, axes = plt.subplots(1, 3, figsize=(14, 4.8))
    for ax, metric, label, scale in zip(
        axes,
        (time_metric, "expanded_nodes", "peak_memory"),
        (
            "Tổng thời gian (ms)" if time_metric == "total_time" else "Thời gian (ms)",
            "Trạng thái mở rộng",
            "Đỉnh cấp phát Python (MiB)",
        ),
        (1000, 1, 1 / 1024**2),
        strict=True,
    ):
        tick_labels = []
        for index, solver in enumerate(solvers):
            values = [
                memory.get((solver, i)) if metric == "peak_memory" else per_map[solver, i][metric]
                for i in sorted(common)
            ]
            values = [v * scale for v in values if v is not None]
            if values:
                bp = ax.boxplot(
                    [values],
                    positions=[index],
                    widths=0.55,
                    patch_artist=True,
                    showfliers=False,
                    medianprops={"color": "#172D42"},
                )
                bp["boxes"][0].set_facecolor(colors[solver])
            tick_labels.append(f"{axis_label(names[solver])}\n(n={len(values)})")
        ax.set_xticks(range(len(solvers)), tick_labels, fontsize=8 if len(solvers) > 4 else 10)
        ax.set_ylabel(label)
        if not common:
            ax.text(0.5, 0.5, "Không có mẫu chung hợp lệ", ha="center", transform=ax.transAxes)
        ax.set_yscale("symlog", linthresh=0.001 if metric == "peak_memory" else 1)
        ax.set_ylim(bottom=0)
        ax.grid(axis="y", alpha=0.2)
    fig.suptitle("Chi phí tìm kiếm theo thuật toán", fontsize=17, weight="bold")
    fig.tight_layout()
    fig.text(
        0.02,
        -0.02,
        f"Cùng tập {len(common)} màn thành công với mọi thuật toán; "
        "hộp: Q1–Q3, vạch: trung vị, râu: 1,5 IQR; ẩn ngoại lệ.",
        fontsize=9,
    )
    save(fig, "03-chi-phi", "Chi phí tìm kiếm theo thuật toán")

    fig, ax = plt.subplots(figsize=(10, 4.5))
    for index, solver in enumerate(solvers):
        values = [
            per_map[solver, i]["length_ratio"]
            for i in sorted(solved[solver])
            if per_map[solver, i]["length_ratio"] is not None
        ]
        if values:
            ax.scatter(
                [index + ((j % 9) - 4) * 0.025 for j in range(len(values))],
                values,
                alpha=0.5,
                s=15,
                color=colors[solver],
            )
        ax.text(index, 0.98, f"n={len(values)}", transform=ax.get_xaxis_transform(), ha="center")
    ax.axhline(1, color="#607D8B", linestyle="--", label="Lời giải tối ưu")
    ax.set_xticks(range(len(solvers)), [axis_label(names[s]) for s in solvers])
    ax.set(ylabel="Độ dài tìm được / độ dài tối ưu", title="Chất lượng lời giải")
    ax.legend()
    save(fig, "04-loi-giai", "Chất lượng lời giải")

    all_positive = [r for r in manifest["records"] if r["family"] != "unsolvable"]
    fig, ax = plt.subplots(figsize=(10, 5.5))
    for family, marker in zip(list(FAMILIES)[:4], ["o", "s", "^", "D"], strict=True):
        group = [r for r in all_positive if r["family"] == family]
        ax.scatter(
            [len(r["certificate"]["path"]) for r in group],
            [r["certificate"]["reachable_states"] for r in group],
            label=FAMILIES[family],
            marker=marker,
            alpha=0.6,
            s=24,
        )
    ax.set(
        xlabel="Độ dài lời giải tối ưu (hành động)",
        ylabel="Số trạng thái đạt tới",
        title="Bản đồ độ phức tạp của bộ dữ liệu",
        yscale="log",
    )
    ax.legend()
    ax.grid(alpha=0.2)
    save(fig, "05-do-phuc-tap", "Bản đồ độ phức tạp của bộ dữ liệu")

    families = [f for f in FAMILIES if f != "unsolvable" and f in manifest["bands"]]
    labels = [f"{FAMILIES[f]} · {b + 1}" for f in families for b in range(3)]
    counts = [
        [
            sum(r["family"] == f and r["band"] == b and r["topology"] == t for r in all_positive)
            for t in TOPOLOGIES
        ]
        for f in families
        for b in range(3)
    ]
    fig, ax = plt.subplots(figsize=(8, 7))
    heat = ax.imshow(counts, cmap="Blues", aspect="auto", vmin=0)
    ax.set_xticks(range(3), list(TOPOLOGIES.values()))
    ax.set_yticks(range(len(labels)), labels)
    ax.set_title("Độ đa dạng của màn chơi", pad=15)
    for r, line in enumerate(counts):
        for c, value in enumerate(line):
            ax.text(
                c,
                r,
                str(value),
                ha="center",
                va="center",
                color="white" if value > max(map(max, counts)) / 2 else "#172D42",
            )
    fig.colorbar(heat, ax=ax, label="Số màn")
    save(fig, "06-da-dang", "Độ đa dạng của màn chơi")

    fig, ax = plt.subplots(figsize=(10, 5))
    reasons = [
        ("accepted", "Chấp nhận"),
        ("duplicate", "Trùng lặp"),
        ("exhausted", "Vô nghiệm"),
        ("unknown", "Chưa xác định"),
        ("unnecessary", "Cơ chế không bắt buộc"),
        ("necessity_unknown", "Chưa chứng minh cơ chế"),
        ("band_full", "Đủ khoảng độ dài"),
        ("topology_full", "Đủ dạng địa hình"),
        ("invalid_path", "Lời giải không hợp lệ"),
    ]
    bottoms = [0] * len(families)
    for reason, label in reasons:
        values = [manifest["generation"][f].get(reason, 0) for f in families]
        if sum(values):
            ax.bar(range(len(families)), values, bottom=bottoms, label=label)
        bottoms = [a + b for a, b in zip(bottoms, values, strict=True)]
    ax.set_xticks(range(len(families)), [FAMILIES[f] for f in families])
    ax.set(ylabel="Số ứng viên", title="Hiệu quả của bộ sinh")
    ax.legend(bbox_to_anchor=(1.02, 1), loc="upper left", fontsize=9)
    save(fig, "07-bo-sinh", "Hiệu quả của bộ sinh")

    fig, axes = plt.subplots(len(families), 3, figsize=(12, 3.2 * len(families)), squeeze=False)
    for fi, family in enumerate(families):
        for band in range(3):
            ax = axes[fi][band]
            candidates = sorted(
                [r for r in all_positive if r["family"] == family and r["band"] == band],
                key=lambda r: (len(r["certificate"]["path"]), r["id"]),
            )
            if not candidates:
                ax.axis("off")
                continue
            record = candidates[len(candidates) // 2]
            data = json.loads((corpus / record["file"]).read_text())
            grid = data["grid"]
            for r, row in enumerate(grid):
                for c, tile in enumerate(row):
                    color = {
                        "#": "#E6EDF2",
                        ".": "white",
                        "F": "#F6C56F",
                        "S": "#0072B2",
                        "G": "#009E73",
                    }[tile]
                    ax.add_patch(
                        Rectangle(
                            (c - 0.5, r - 0.5),
                            1,
                            1,
                            facecolor=color,
                            edgecolor="#C6D2DB",
                            linewidth=0.3,
                        )
                    )
                    if tile in "SG":
                        ax.text(c, r, tile, ha="center", va="center", color="white", fontsize=8)
            for bridge in data["bridges"]:
                for r, c in bridge["cells"]:
                    ax.add_patch(
                        Rectangle(
                            (c - 0.5, r - 0.5), 1, 1, fill=False, edgecolor="#009E73", hatch="///"
                        )
                    )
            for switch in data["switches"]:
                r, c = switch["position"]
                ax.text(
                    c,
                    r,
                    {"soft": "●", "heavy": "×", "split": "T"}[switch["type"]],
                    ha="center",
                    va="center",
                    color="#8B5DB5",
                    fontsize=10,
                )
                for label, (r, c) in zip("AB", switch.get("spawn_positions", []), strict=False):
                    ax.text(c, r, label, ha="center", va="center", color="#8B5DB5", fontsize=8)
            ax.set(xlim=(-0.5, len(grid[0]) - 0.5), ylim=(len(grid) - 0.5, -0.5), aspect="equal")
            ax.set_title(
                f"{FAMILIES[family]} · khoảng {band + 1}\n"
                f"{len(record['certificate']['path'])} bước",
                fontsize=10,
            )
            ax.tick_params(labelsize=6)
    fig.suptitle("Bộ sưu tập màn chơi tiêu biểu", fontsize=18, weight="bold")
    fig.tight_layout(rect=(0, 0.04, 1, 0.96))
    fig.text(
        0.05,
        0.01,
        "S: bắt đầu · G: đích · cam: ô dễ vỡ · gạch chéo: cầu · "
        "●: công tắc nhẹ · ×: công tắc nặng · T: tách khối · A/B: vị trí xuất hiện",
        fontsize=9,
    )
    save(fig, "08-man-tieu-bieu", "Bộ sưu tập màn chơi tiêu biểu")

    def diagram(filename, title, labels):
        fig, ax = plt.subplots(figsize=(12, 4.5))
        ax.set(xlim=(0, 12), ylim=(0, 4))
        ax.axis("off")
        ax.set_title(title, fontsize=18, pad=16)
        positions = [(0.2, 2.4), (4.2, 2.4), (8.2, 2.4), (8.2, 0.5), (4.2, 0.5), (0.2, 0.5)]
        for index, ((x, y), label) in enumerate(zip(positions, labels, strict=True)):
            ax.add_patch(
                FancyBboxPatch(
                    (x, y),
                    3.3,
                    1,
                    boxstyle="round,pad=.12",
                    facecolor="#E4F0F7",
                    edgecolor="#0072B2",
                )
            )
            ax.text(
                x + 1.65,
                y + 0.5,
                f"{index + 1:02d}  {label}",
                ha="center",
                va="center",
                fontsize=11,
            )
        for index in range(5):
            x, y = positions[index]
            nx, ny = positions[index + 1]
            if ny == y:
                direction = 1 if nx > x else -1
                start = (x + (3.45 if direction == 1 else -0.15), y + 0.5)
                end = (nx + (-0.15 if direction == 1 else 3.45), ny + 0.5)
            else:
                start, end = (x + 1.65, y - 0.15), (nx + 1.65, ny + 1.15)
            ax.annotate(
                "",
                xy=end,
                xytext=start,
                arrowprops={"arrowstyle": "->", "color": "#0072B2", "lw": 2},
            )
        save(fig, filename, title)

    diagram(
        "09-quy-trinh-sinh",
        "Quy trình sinh và kiểm chứng màn chơi",
        [
            "Cấu hình và seed",
            "Sinh ứng viên",
            "Kiểm tra định dạng",
            "Giải và kiểm chứng\ncơ chế bắt buộc",
            "Loại trùng và phân tập",
            "Lưu dữ liệu cố định",
        ],
    )
    diagram(
        "10-quy-trinh-do",
        "Quy trình đo hiệu năng thuật toán",
        [
            "Kiểm tra mã băm\nbộ dữ liệu",
            "Tiến trình độc lập",
            "Đo thời gian / bộ nhớ\nở lượt riêng",
            "Kiểm tra lời giải",
            "Tổng hợp dữ liệu thô",
            "Xuất báo cáo\nvà biểu đồ",
        ],
    )

    lines = [
        "# Báo cáo benchmark Bloxorz",
        "",
        "## Điều kiện thực nghiệm",
        "",
        f"- Bộ dữ liệu: `{manifest['corpus_hash']}`.",
        f"- Phân tập: `{metadata['partition']}`; {len(records)} màn được đo.",
        f"- {metadata['repeats']} lượt thời gian và 1 lượt bộ nhớ cho mỗi thuật toán/màn.",
        f"- Giới hạn: {metadata['timeout']} giây khởi tạo và tìm kiếm, {metadata['memory_mib']} MiB "
        "không gian địa chỉ tiến trình trên Linux.",
        "- Chi phí mỗi hành động bằng 1; UCS dùng chế độ unit.",
        "- Thời gian không bật tracing; bộ nhớ là đỉnh cấp phát Python, không phải RSS.",
        f"- Phạm vi đo bộ nhớ: `{metadata.get('measurement_scope', 'search_only')}`.",
        "- Mỗi mẫu trong biểu đồ chi phí là trung vị các lượt của một màn.",
        "- Tỷ lệ thành công yêu cầu mọi lượt thời gian đều giải đúng màn đó.",
        f"- So sánh chi phí dùng chung {len(common)} màn thành công với mọi thuật toán.",
        "- Độ phức tạp tìm kiếm không đại diện trực tiếp cho độ khó với người chơi.",
        "",
        "## Kết quả theo thuật toán",
        "",
        (
            "| Thuật toán | Giải được / có lời giải | Trung vị tổng thời gian (ms), tập chung |"
            if time_metric == "total_time"
            else "| Thuật toán | Giải được / có lời giải | Trung vị tìm kiếm (ms), tập chung |"
        ),
        "|---|---:|---:|",
    ]
    for solver in solvers:
        values = [per_map[solver, i][time_metric] * 1000 for i in common]
        median = f"{statistics.median(values):.3f}" if values else "Không có dữ liệu"
        lines.append(f"| {names[solver]} | {len(solved[solver])}/{len(positive)} | {median} |")
    lines += [
        "",
        "## Khởi tạo heuristic và tổng thời gian",
        "",
        "| Thử nghiệm | Khởi tạo (ms) | Tìm kiếm (ms) | Tổng (ms) |",
        "|---|---:|---:|---:|",
    ]
    for solver in solvers:
        medians = []
        for metric in ("initialization_time", "search_time", "total_time"):
            values = [
                per_map[solver, i][metric] * 1000
                for i in common
                if per_map[solver, i][metric] is not None
            ]
            medians.append(f"{statistics.median(values):.3f}" if values else "—")
        lines.append(f"| {names[solver]} | " + " | ".join(medians) + " |")
    lines += [
        "",
        "## Kết quả theo nhóm và khoảng độ dài",
        "",
        "| Nhóm | Khoảng | Thuật toán | Giải được / tổng | "
        + ("Tổng thời gian (ms)" if time_metric == "total_time" else "Tìm kiếm (ms)")
        + " | Mở rộng | Bộ nhớ (MiB) | Độ dài / tối ưu |",
        "|---|---:|---|---:|---:|---:|---:|---:|",
    ]
    for family in families:
        for band in range(3):
            ids = {r["id"] for r in records if r["family"] == family and r["band"] == band}
            for solver in solvers:
                values = [per_map[solver, i][time_metric] * 1000 for i in ids & common]
                median = f"{statistics.median(values):.3f}" if values else "—"
                expansions = [per_map[solver, i]["expanded_nodes"] for i in ids & common]
                allocations = [
                    memory[solver, i] / 1024**2
                    for i in ids & common
                    if memory.get((solver, i)) is not None
                ]
                ratios = [
                    per_map[solver, i]["length_ratio"]
                    for i in ids & solved[solver]
                    if per_map[solver, i]["length_ratio"] is not None
                ]

                def show(values):
                    return f"{statistics.median(values):.3f}" if values else "—"

                lines.append(
                    f"| {FAMILIES[family]} | {band + 1} | {names[solver]} | "
                    f"{len(ids & solved[solver])}/{len(ids)} | {median} | "
                    f"{show(expansions)} | {show(allocations)} | {show(ratios)} |"
                )
    lines += [
        "",
        "## Trạng thái từng lượt đo thời gian",
        "",
        "| Thuật toán | " + " | ".join(STATUS.values()) + " |",
        "|---|" + "---:|" * len(STATUS),
    ]
    for solver in solvers:
        counts = Counter(r["status"] for r in timing if r["solver"] == solver)
        lines.append(f"| {names[solver]} | " + " | ".join(str(counts[s]) for s in STATUS) + " |")
    lines += [
        "",
        "## Trạng thái từng lượt đo bộ nhớ",
        "",
        "| Thuật toán | " + " | ".join(STATUS.values()) + " |",
        "|---|" + "---:|" * len(STATUS),
    ]
    for solver in solvers:
        counts = Counter(
            r["status"] for r in rows if r["solver"] == solver and r["mode"] == "memory"
        )
        lines.append(f"| {names[solver]} | " + " | ".join(str(counts[s]) for s in STATUS) + " |")
    lines += [
        "",
        "## Bộ kiểm tra vô nghiệm",
        "",
        "| Thuật toán | Kết luận vô nghiệm đúng / lượt kiểm tra |",
        "|---|---:|",
    ]
    for solver in solvers:
        neg = [r for r in timing if r["family"] == "unsolvable" and r["solver"] == solver]
        lines.append(
            f"| {names[solver]} | {sum(r['status'] == 'exhausted' for r in neg)}/{len(neg)} |"
        )
    lines += [
        "",
        "## Giới hạn và độ phủ",
        "",
        "Chỉ nhận màn được chứng nhận trong ngân sách trạng thái; các màn vượt ngân sách "
        "không đại diện trong tập này. Biểu đồ bộ sinh không gồm ứng viên hiệu chỉnh ban đầu.",
        "Các khoảng độ dài được hiệu chỉnh riêng theo từng cơ chế; cùng số thứ tự khoảng "
        "không có nghĩa là cùng độ khó giữa các cơ chế.",
        "",
        "| Nhóm | Ngưỡng khoảng 1 / 2 | Số màn còn thiếu |",
        "|---|---|---:|",
    ]
    for family in families:
        lines.append(
            f"| {FAMILIES[family]} | {manifest['bands'][family]} | "
            f"{sum(manifest['shortfalls'][family].values())} |"
        )
    for filename, title in images:
        lines += [
            "",
            f"## {title}",
            "",
            f"![{title}]({filename}.png)",
            "",
            f"[Bản vector SVG]({filename}.svg)",
        ]
    lines += [
        "",
        "## Nguồn dữ liệu",
        "",
        "Dữ liệu thô và cấu hình được sao chép vào thư mục "
        "`data/` bên cạnh báo cáo; có thể tạo lại biểu đồ mà không chạy solver.",
        "",
    ]
    (output / "bao-cao.md").write_text("\n".join(lines), encoding="utf-8")
    data_dir = output / "data"
    data_dir.mkdir(exist_ok=True)
    for name in ("metadata.json", "runs.jsonl", "runs.csv"):
        source = results / name
        if source.exists():
            (data_dir / name).write_bytes(source.read_bytes())
    (data_dir / "manifest.json").write_bytes((corpus / "manifest.json").read_bytes())
