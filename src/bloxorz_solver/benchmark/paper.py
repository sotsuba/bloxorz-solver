"""Publication figures: exact Times New Roman, fixed physical sizes, white background."""

import csv
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
from matplotlib import font_manager
from matplotlib.backends.backend_pdf import PdfPages
from matplotlib.ft2font import FT2Font
from matplotlib.patches import Circle, Rectangle
from matplotlib.ticker import FuncFormatter, NullFormatter

from bloxorz_solver.benchmark.experiments import axis_label, report_view
from bloxorz_solver.benchmark.runner import read_manifest

COLORS = ("#0072B2", "#D55E00", "#009E73", "#7A5195")
MARKERS = ("o", "s", "^", "D")
STYLES = ("-", "--", "-.", ":")
NAMES = {"bfs": "BFS", "dfs": "DFS", "ucs": "UCS", "astar": "A*"}
FAMILIES = {
    "dependency": "Chuỗi phụ thuộc",
    "shared": "Cầu dùng chung",
    "split_bridge": "Tách khối và cầu",
    "ordinary": "Ô thường",
    "fragile": "Ô dễ vỡ",
    "switch": "Công tắc và cầu",
    "split": "Tách khối",
}


def find_times(font_dir=None):
    candidates = []
    if font_dir:
        directory = Path(font_dir)
        if not directory.is_dir():
            raise ValueError(f"Font directory does not exist: {directory}")
        candidates = sorted(directory.rglob("*.ttf")) + sorted(directory.rglob("*.otf"))
    else:
        candidates = [Path(p) for p in font_manager.findSystemFonts()]
        # Include freshly installed fonts even when Matplotlib's cache predates installation.
        for directory in (Path.home() / ".local/share/fonts", Path.home() / ".fonts"):
            if directory.exists():
                candidates += list(directory.rglob("*.ttf"))
    for path in candidates:
        try:
            face = FT2Font(str(path))
        except (RuntimeError, OSError):
            # System font inventories can include unsupported or stale files.
            continue
        if face.family_name == "Times New Roman" and face.style_name.lower() in (
            "regular",
            "normal",
        ):
            required = set(
                "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789"
                "ÀÁẢÃẠĂẰẮẲẴẶÂẦẤẨẪẬÈÉẺẼẸÊỀẾỂỄỆÌÍỈĨỊÒÓỎÕỌÔỒỐỔỖỘƠỜỚỞỠỢ"
                "ÙÚỦŨỤƯỪỨỬỮỰỲÝỶỸỴĐàáảãạăằắẳẵặâầấẩẫậèéẻẽẹêềếểễệìíỉĩị"
                "òóỏõọôồốổỗộơờớởỡợùúủũụưừứửữựỳýỷỹỵđ/%()[]:.,+-=*"
            )
            if any(ord(char) not in face.get_charmap() for char in required):
                raise ValueError(f"Times New Roman lacks required Vietnamese glyphs: {path}")
            font_manager.fontManager.addfont(str(path))
            return path.resolve()
    raise ValueError(
        "Times New Roman Regular is required. Install it or pass --font-dir; no font substitution is allowed."
    )


def load_data(corpus, results):
    manifest = read_manifest(corpus)
    metadata = json.loads((results / "metadata.json").read_text())
    if metadata["corpus_hash"] != manifest["corpus_hash"]:
        raise ValueError("Result/corpus hash mismatch")
    selected = set(metadata["selected_ids"])
    records = {r["id"]: r for r in manifest["records"] if r["id"] in selected}
    if set(records) != selected:
        raise ValueError("Unknown selected IDs")
    rows = [json.loads(s) for s in (results / "runs.jsonl").read_text().splitlines()]
    metadata, rows, _ = report_view(metadata, rows)
    seen = {}
    for row in rows:
        key = row["id"], row["solver"], row["mode"], row["repetition"]
        if key in seen or row["id"] not in records or row["solver"] not in metadata["solvers"]:
            raise ValueError("Duplicate or unexpected result row")
        seen[key] = row
    for identity in selected:
        for solver in metadata["solvers"]:
            for mode, count in (("timing", metadata["repeats"]), ("memory", 1)):
                for repetition in range(count):
                    key = identity, solver, mode, repetition
                    if key not in seen:
                        seen[key] = {
                            "id": identity,
                            "solver": solver,
                            "mode": mode,
                            "repetition": repetition,
                            "status": "not_run",
                        }
    return manifest, metadata, records, list(seen.values())


def aggregate(records, rows, solvers, repeats):
    timing = defaultdict(list)
    memory = {}
    for row in rows:
        if row["mode"] == "timing":
            timing[row["id"], row["solver"]].append(row)
        elif row["status"] == "solved":
            memory[row["id"], row["solver"]] = row.get("peak_memory")
    samples = {}
    for key, runs in timing.items():
        if len(runs) == repeats and all(r["status"] == "solved" for r in runs):
            record = records[key[0]]
            certificate = record["certificate"]
            optimal = certificate.get("optimal_length")
            if optimal is None and certificate["status"] == "solved":
                optimal = len(certificate["path"])
            samples[key] = {
                "id": key[0],
                "solver": key[1],
                "bridges": record.get("bridges", 0),
                "family": record["family"],
                "cohort": record.get("cohort", "standard"),
                "search_time": statistics.median(r["search_time"] for r in runs),
                "initialization_time": statistics.median(r["initialization_time"] for r in runs)
                if all(r.get("initialization_time") is not None for r in runs)
                else None,
                "total_time": statistics.median(r["total_time"] for r in runs)
                if all(r.get("total_time") is not None for r in runs)
                else None,
                "expanded_nodes": statistics.median(r["expanded_nodes"] for r in runs),
                "peak_memory": memory.get(key),
                "length": statistics.median(r["solution_length"] for r in runs),
                "ratio": statistics.median(r["solution_length"] for r in runs) / optimal
                if optimal
                else None,
            }
    common = {identity for identity in records if all((identity, s) in samples for s in solvers)}
    return samples, common


def table(path, rows):
    fields = sorted({key for row in rows for key in row})
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(
            {
                k: json.dumps(v, ensure_ascii=False) if isinstance(v, (dict, list)) else v
                for k, v in row.items()
            }
            for row in rows
        )


COHORTS = {"standard": "Tập chuẩn", "challenge": "Tập thử thách"}
FIGURE_NAMES = {
    "01-hieu-nang",
    "02-ty-le-giai",
    "03-chat-luong",
    "04-khoang-nghiem",
    "05-do-phu",
    "06-co-che",
    "07-tai-nguyen",
}
QUESTIONS = {
    "05-do-phu": (
        "Bộ dữ liệu gồm những nhóm màn nào?",
        "Số màn và quy mô đồ thị cho biết phạm vi so sánh; không đo độ khó với người chơi.",
    ),
    "01-hieu-nang": (
        "Thời gian và tài nguyên của từng thuật toán",
        "Đọc tên thuật toán và giá trị ở cuối thanh; thanh ngắn hơn là chi phí thấp hơn.",
    ),
    "02-ty-le-giai": (
        "Trong cùng ngân sách thời gian, thuật toán giải được bao nhiêu màn?",
        "Đường cao hơn tại cùng mốc thời gian nghĩa là giải được nhiều màn hơn.",
    ),
    "03-chat-luong": (
        "Lời giải tìm được dài hơn lời giải tối ưu bao nhiêu?",
        "Tỷ số bằng 1 là tối ưu; bằng 2 nghĩa là cần gấp đôi số hành động.",
    ),
    "04-khoang-nghiem": (
        "Với màn chưa biết tối ưu, lời giải quan sát nằm trong khoảng nào?",
        "Cận dưới và đường chứng kiến giới hạn khoảng nghiệm; điểm quan sát không chứng minh tối ưu.",
    ),
    "06-co-che": (
        "Công tắc và cầu liên hệ thế nào trên một màn cụ thể?",
        "Đọc vị trí trên bản đồ cùng mã công tắc/cầu tương ứng ở sơ đồ bên cạnh.",
    ),
    "07-tai-nguyen": (
        "Tài nguyên hệ thống thay đổi thế nào khi sinh corpus?",
        "Đây là số đo toàn hệ thống trong pha sinh, không phải chi phí tìm kiếm của solver.",
    ),
}


def is_solvable(record):
    """Include witnessed challenge maps even without an optimal certificate path."""
    return record["family"] != "unsolvable" and (
        record["certificate"].get("path") is not None or record.get("witness") is not None
    )


def overview(manifest, meta, records, rows, samples, common, names):
    """Ground the reading guide and observations in the selected measurements."""
    metric = "total_time" if meta.get("measurement_scope") else "search_time"
    eligible = {i for i, r in records.items() if is_solvable(r)}
    statuses = Counter(r["status"] for r in rows)
    status_labels = {
        "solved": "giải được",
        "exhausted": "kết luận vô nghiệm",
        "timeout": "hết thời gian",
        "memory_limit": "vượt bộ nhớ",
        "invalid_path": "đường đi sai",
        "error": "lỗi",
        "not_run": "chưa chạy",
    }
    lines = [
        "# Bộ hình benchmark Bloxorz - hướng dẫn đọc và trình bày",
        "",
        "## Mục tiêu và phạm vi",
        "",
        "So sánh tốc độ, chi phí tìm kiếm và chất lượng lời giải của các thuật toán "
        "trên cùng bộ màn Bloxorz. Các hình được sắp theo mạch: dữ liệu → hiệu năng → "
        "chất lượng lời giải → ví dụ cơ chế.",
        "",
        f"- Corpus đầy đủ: **{len(manifest['records'])} màn**; tập được chọn đo: "
        f"**{len(records)} màn**, gồm {len(eligible)} màn biết có lời giải và "
        f"{sum(r['family'] == 'unsolvable' for r in records.values())} màn vô nghiệm.",
        f"- Phân tập: `{meta.get('partition', 'không ghi')}`. Mỗi thuật toán/màn có "
        f"{meta['repeats']} lượt thời gian và 1 lượt bộ nhớ; ngân sách đo "
        f"{meta['timeout']:g} giây/lượt.",
        "- Thuật toán: " + "; ".join(names.values()) + ".",
        f"- Có **{len(common)} màn thành công chung** của mọi thuật toán ở mọi lượt thời gian. "
        "So sánh chi phí chỉ dùng tập chung; bộ nhớ còn yêu cầu mọi thuật toán có số đo hợp lệ.",
        "- Thời gian dùng trung vị các lượt của từng màn, sau đó tổng hợp giữa các màn. "
        + (
            "Tổng thời gian gồm khởi tạo heuristic và tìm kiếm."
            if metric == "total_time"
            else "Dữ liệu cũ chỉ đo thời gian tìm kiếm."
        ),
        "- Bộ nhớ là đỉnh cấp phát Python đo ở lượt riêng, không phải RAM toàn tiến trình (RSS). "
        "Số trạng thái mở rộng tuân theo bộ đếm từng solver; không đồng nghĩa số cạnh đã xét.",
        f"- Lượt chưa chạy: **{sum(r['status'] == 'not_run' for r in rows)}**. "
        "Timeout, lỗi và mẫu thiếu không được đổi thành thời gian bằng 0.",
        "- Trạng thái lượt đo (gộp thời gian và bộ nhớ): "
        + "; ".join(
            f"{status_labels.get(status, status)}: {count}"
            for status, count in sorted(statuses.items())
        )
        + ".",
        "",
        "## Kết quả chính trên tập đã đo",
        "",
        "| Thuật toán | Màn giải được / biết có lời giải | Trung vị thời gian (ms), tập chung | "
        "Trung vị độ dài / tối ưu |",
        "|---|---:|---:|---:|",
    ]
    times_by_solver = {}
    for solver in meta["solvers"]:
        success = sum((i, solver) in samples for i in eligible)
        times = [
            samples[i, solver][metric] * 1000
            for i in common
            if samples[i, solver][metric] is not None
        ]
        ratios = [
            v["ratio"]
            for v in samples.values()
            if v["solver"] == solver and v["cohort"] == "standard" and v["ratio"] is not None
        ]
        time = f"{statistics.median(times):.3f}" if times else "không có mẫu chung"
        ratio = f"{statistics.median(ratios):.3f}" if ratios else "chưa biết tối ưu"
        if times:
            times_by_solver[solver] = statistics.median(times)
        lines.append(f"| {names[solver]} | {success}/{len(eligible)} | {time} | {ratio} |")
    if times_by_solver:
        fastest = min(times_by_solver, key=times_by_solver.get)
        lines += [
            "",
            f"**Quan sát:** {names[fastest]} có trung vị thời gian nhỏ nhất "
            f"trên {len(common)} màn chung: {times_by_solver[fastest]:.3f} ms. "
            "Đây là so sánh mô tả của thí nghiệm này, không phải kết luận nhanh nhất trong mọi trường hợp.",
        ]
    lines += [
        "",
        "**Khi trình bày:** đọc tốc độ cùng chất lượng lời giải. "
        "Một thuật toán trả lời nhanh vẫn có thể cho đường đi dài hơn tối ưu. "
        "Bảng chất lượng dùng các màn có nghiệm tối ưu đã chứng nhận; cỡ mẫu thành công "
        "có thể khác nhau giữa thuật toán.",
        "",
    ]
    return lines


def figure_observation(name, data, names):
    if name == "01-hieu-nang":
        return (
            f"Có {len(data)} giá trị trung vị; cỡ mẫu của từng thanh nằm trong bảng dưới và CSV. "
            "Các thuật toán được so sánh trên cùng tập màn thành công."
        )
    if name == "02-ty-le-giai":
        endpoints = {(r["cohort"], r["solver"]): r for r in data}
        return (
            "; ".join(
                f"{COHORTS[c]} / {names[s]}: {r['percent']:.1f}% trên {r['denominator']} màn"
                for (c, s), r in endpoints.items()
            )
            + "."
        )
    if name == "03-chat-luong":
        return (
            "; ".join(
                f"{names[s]}: n={len(values)}, trung vị={statistics.median(values):.3f}"
                for s in names
                if (values := [r["ratio"] for r in data if r["solver"] == s])
            )
            + ". Các cỡ mẫu này chỉ gồm màn giải thành công có nghiệm tối ưu đã biết."
        )
    if name == "05-do-phu":
        return (
            f"Corpus có {sum(r['count'] for r in data)} màn biết có lời giải "
            f"trong {len({r['family'] for r in data})} nhóm cơ chế. "
            "Hình mô tả toàn corpus; kết quả solver chỉ dùng phân tập được chọn đo."
        )
    if name == "04-khoang-nghiem":
        return f"Có {len(data)} màn thử thách; {sum(r['best_observed'] is not None for r in data)} màn có lời giải quan sát."
    if name == "06-co-che":
        return (
            f"Màn `{data[0]['map_id']}` có {len(data)} liên kết tác động công tắc-cầu. "
            "Đây là ví dụ minh họa, không đại diện cho độ khó của toàn bộ corpus."
        )
    return f"Có {len(data)} mẫu tài nguyên được ghi nhận trong pha sinh."


def create_figures(corpus, results, output, *, font_dir=None):
    font = find_times(font_dir)
    manifest, meta, records, rows = load_data(corpus, results)
    solvers = meta["solvers"]
    _, _, names = report_view(meta, [])
    colors = [plt.get_cmap("tab10")(i % 10) for i in range(len(solvers))]
    samples, common = aggregate(records, rows, solvers, meta["repeats"])
    output.mkdir(parents=True, exist_ok=True)
    (output / "data").mkdir(exist_ok=True)
    captions, outputs, skipped = [], [], []
    cohorts = [
        c
        for c in COHORTS
        if any(r.get("cohort", "standard") == c and is_solvable(r) for r in records.values())
    ]
    if "challenge" not in cohorts:
        skipped.append(
            {"name": "panels-challenge", "reason": "Tập được chọn đo không có màn thử thách."}
        )
    if "standard" not in cohorts:
        skipped.append(
            {
                "name": "panels-standard",
                "reason": "Tập được chọn đo không có màn chuẩn có lời giải.",
            }
        )
    missing_reasons = {
        "01-hieu-nang": "Không có mẫu thành công chung đủ số đo; n=0. Xem trạng thái lượt đo trong data/all-runs.csv.",
        "02-ty-le-giai": "Không có màn biết có lời giải trong tập được chọn đo.",
        "03-chat-luong": "Không có lời giải thành công với nghiệm tối ưu đã chứng nhận trên tập chuẩn.",
        "04-khoang-nghiem": "Tập được chọn đo không có màn thử thách.",
        "05-do-phu": "Corpus không có màn biết có lời giải.",
        "06-co-che": "Corpus không có ví dụ liên kết công tắc-cầu.",
        "07-tai-nguyen": "Không thu thập telemetry tài nguyên pha sinh; không thể dựng lại từ kết quả solver.",
    }
    style = {
        "font.family": "Times New Roman",
        "font.weight": "normal",
        "font.size": 8,
        "axes.labelsize": 9,
        "axes.titlesize": 9,
        "legend.fontsize": 8,
        "xtick.labelsize": 8,
        "ytick.labelsize": 8,
        "figure.facecolor": "white",
        "axes.facecolor": "white",
        "savefig.facecolor": "white",
        "text.color": "black",
        "axes.labelcolor": "black",
        "axes.edgecolor": "black",
        "axes.spines.top": False,
        "axes.spines.right": False,
        "axes.linewidth": 0.6,
        "lines.linewidth": 1.1,
        "lines.markersize": 3,
        "pdf.fonttype": 42,
        "ps.fonttype": 42,
        "svg.fonttype": "path",
        "axes.unicode_minus": False,
        "svg.hashsalt": "bloxorz-paper-v2",
    }
    with plt.rc_context(style), PdfPages(output / "bo-hinh.pdf") as collection:

        def figure(width=178, height=70, **kwargs):
            return plt.subplots(
                figsize=(width / 25.4, height / 25.4), layout="constrained", **kwargs
            )

        def save(fig, name, caption, data):
            if not data:
                skipped.append({"name": name, "reason": missing_reasons[name]})
                plt.close(fig)
                return
            question, reading = QUESTIONS[name]
            fig.suptitle(question, fontsize=10)
            # Force every text object onto the verified face, including tick labels.
            from matplotlib.text import Text

            fig.canvas.draw()
            for text in fig.findobj(Text):
                text.set_fontproperties(
                    font_manager.FontProperties(fname=str(font), size=text.get_fontsize())
                )
            for extension in ("pdf", "svg", "png"):
                options = {"dpi": 600} if extension == "png" else {}
                if extension in ("pdf", "svg"):
                    options["metadata"] = (
                        {"Creator": "Bloxorz benchmark"} if extension == "pdf" else {"Date": None}
                    )
                fig.savefig(output / f"{name}.{extension}", **options)
            collection.savefig(fig)
            table(output / "data" / f"{name}.csv", data)
            number = len(captions) + 1
            details = (
                f"## Hình {number}. {question}\n\n"
                f"**Cách đọc:** {reading}\n\n{caption}\n\n"
                f"![Hình {number}: {question}]({name}.png)\n\n"
                f"**Quan sát từ dữ liệu:** {figure_observation(name, data, names)}\n\n"
            )
            if name == "01-hieu-nang":
                details += (
                    "| Tập | Nhóm cơ chế | Chỉ số | n chung mỗi thuật toán |\n|---|---|---|---:|\n"
                )
                counts = {(r["cohort"], r["family"], r["metric"]): r["sample_count"] for r in data}
                units = {r["metric"]: r["unit"] for r in data}
                for (cohort, family, metric), count in counts.items():
                    details += f"| {COHORTS[cohort]} | {FAMILIES.get(family, 'Tất cả cơ chế')} | {units[metric]} | {count} |\n"
                details += "\n"
            details += f"[PDF]({name}.pdf) · [SVG]({name}.svg) · [PNG]({name}.png) · [CSV](data/{name}.csv)\n"
            captions.append(details)
            outputs.append(
                {
                    "name": name,
                    "number": number,
                    "title": question,
                    "data_rows": len(data),
                    "width_mm": fig.get_figwidth() * 25.4,
                    "height_mm": fig.get_figheight() * 25.4,
                }
            )
            plt.close(fig)

        def panel(ax, letter):
            ax.set_title(f"({letter})", loc="left", fontsize=10)
            ax.grid(axis="y", color=".87", linewidth=0.4)

        def number_axes(ax, axis="y"):
            formatter = FuncFormatter(lambda value, pos: f"{value:g}")
            (ax.yaxis if axis == "y" else ax.xaxis).set_major_formatter(formatter)

        skipped.append(
            {
                "name": "05-do-phu",
                "reason": "Bỏ hình nhóm/khoảng và quy mô đồ thị khỏi bộ hình chính; cấu trúc dữ liệu có trong manifest corpus.",
            }
        )
        fig, axes = figure(
            height=max(85, 24 + 8 * len(solvers)) * max(1, len(cohorts)),
            nrows=max(1, len(cohorts)),
            ncols=3,
            squeeze=False,
        )
        metrics = [
            (
                "total_time" if meta.get("measurement_scope") else "search_time",
                "Tổng thời gian (ms)" if meta.get("measurement_scope") else "Tìm kiếm (ms)",
                1000,
            ),
            ("expanded_nodes", "Trạng thái mở rộng", 1),
            ("peak_memory", "Cấp phát Python (MiB)", 1 / 1024**2),
        ]
        cost_data = []
        for ci, cohort in enumerate(cohorts):
            families = ["all"]
            for mi, (metric, label, factor) in enumerate(metrics):
                ax = axes[ci, mi]
                valid_ids = {
                    i for i in common if all(samples[i, s][metric] is not None for s in solvers)
                }
                ax.set_title(f"({chr(97 + ci * 3 + mi)}) {COHORTS[cohort]}", fontsize=9)
                ax.grid(axis="x", color=".87", linewidth=0.4)
                for family in families:
                    ids = {i for i in valid_ids if records[i].get("cohort", "standard") == cohort}
                    for si, solver in enumerate(solvers):
                        values = [samples[i, solver][metric] * factor for i in ids]
                        if not values:
                            continue
                        median = statistics.median(values)
                        ax.barh(si, median, color=colors[si], height=0.65)
                        ax.annotate(f" {median:,.3f}", (median, si), va="center", fontsize=8)
                        cost_data.append(
                            dict(
                                cohort=cohort,
                                family=family,
                                solver=solver,
                                metric=metric,
                                median=median,
                                sample_count=len(ids),
                                sample_ids=sorted(ids),
                                unit=label,
                            )
                        )
                ax.set_yticks(range(len(solvers)), [names[s] for s in solvers])
                ax.set_ylim(len(solvers) - 0.5, -0.5)
                ax.set_xlabel(label)
                if any(r["cohort"] == cohort and r["metric"] == metric for r in cost_data):
                    ax.set_title(f"{COHORTS[cohort]} · n={len(ids)} màn chung", fontsize=9)
                    ax.set_xlim(left=0)
                    ax.margins(x=0.35)
                    number_axes(ax, "x")
                else:
                    skipped.append(
                        {
                            "name": f"01-hieu-nang/{cohort}/{metric}",
                            "reason": "n=0: không có mẫu chung hợp lệ; xem trạng thái lượt đo trong CSV.",
                        }
                    )
                    ax.set_axis_off()
                    ax.text(
                        0.5,
                        0.5,
                        "n=0: không có mẫu chung hợp lệ\nXem trạng thái lượt đo trong CSV",
                        ha="center",
                        va="center",
                        transform=ax.transAxes,
                        fontsize=8,
                    )
        save(
            fig,
            "01-hieu-nang",
            "Mỗi thanh là trung vị trên cùng tập màn; số cuối thanh là giá trị đo. "
            "Trục tuyến tính bắt đầu từ 0; thanh ngắn hơn là chi phí thấp hơn. "
            "Chỉ dùng màn mọi thuật toán đều giải thành công ở mọi lượt thời gian; "
            "bộ nhớ yêu cầu thêm số đo hợp lệ của tất cả thuật toán. "
            "Thời gian và bộ nhớ đo riêng. Xem thêm tỷ lệ giải để đánh giá màn thất bại.",
            cost_data,
        )

        fig, axes = figure(height=80, ncols=max(1, len(cohorts)), squeeze=False)
        cdf_data = []
        for ci, cohort in enumerate(cohorts):
            ax = axes[0, ci]
            panel(ax, chr(97 + ci))
            ids = {
                i
                for i, r in records.items()
                if r.get("cohort", "standard") == cohort and is_solvable(r)
            }
            for si, solver in enumerate(solvers):
                times = sorted(
                    samples[i, solver][
                        "total_time" if meta.get("measurement_scope") else "search_time"
                    ]
                    for i in ids
                    if (i, solver) in samples
                )
                xs = [0, *times, meta["timeout"]]
                ys = [
                    0,
                    *[100 * (j + 1) / max(1, len(ids)) for j in range(len(times))],
                    100 * len(times) / max(1, len(ids)),
                ]
                ax.step(
                    xs,
                    ys,
                    where="post",
                    color=colors[si],
                    linestyle=STYLES[si % len(STYLES)],
                    label=names[solver],
                )
                cdf_data += [
                    {
                        "cohort": cohort,
                        "solver": solver,
                        "seconds": x,
                        "percent": y,
                        "denominator": len(ids),
                    }
                    for x, y in zip(xs, ys, strict=True)
                ]
            ax.set(
                xlabel="Tổng thời gian (giây)"
                if meta.get("measurement_scope")
                else "Thời gian (giây)",
                ylabel="Màn giải được (%)",
                ylim=(0, 102),
                xlim=(0, meta["timeout"]),
            )
            ax.set_xscale("symlog", linthresh=0.001)
            number_axes(ax, "x")
            ax.set_title(
                f"({chr(97 + ci)}) {COHORTS[cohort]} - n={len(ids)}", loc="left", fontsize=9
            )
            ax.legend(frameon=False, fontsize=7)
            if not ids:
                ax.text(0.5, 0.5, "Không có mẫu", ha="center", transform=ax.transAxes)
        not_run = sum(r["status"] == "not_run" for r in rows)
        save(
            fig,
            "02-ty-le-giai",
            "Mỗi panel tương ứng một tập có dữ liệu, cỡ mẫu n được ghi trên hình. "
            "Một màn chỉ được tính giải thành công khi mọi lượt đo thời gian đều thành công. "
            "Mẫu số là toàn bộ màn biết có lời giải trong tập được chọn, kể cả màn có lượt thất bại hoặc chưa chạy; "
            f"toàn thí nghiệm có {not_run} lượt chưa chạy. Trục thời gian dùng symlog.",
            cdf_data,
        )

        fig, ax = figure(width=178 if len(solvers) > 4 else 85, height=68)
        quality = [
            v for v in samples.values() if v["cohort"] == "standard" and v["ratio"] is not None
        ]
        for si, solver in enumerate(solvers):
            values = [v["ratio"] for v in quality if v["solver"] == solver]
            ax.scatter(
                [si + ((j % 7) - 3) * 0.025 for j in range(len(values))],
                values,
                marker=MARKERS[si % len(MARKERS)],
                color=colors[si],
                s=9,
                alpha=0.65,
            )
        ax.axhline(1, color="black", linestyle="--", linewidth=0.6)
        ax.set_xticks(
            range(len(solvers)),
            [
                axis_label(names[s]) + f"\n(n={sum(v['solver'] == s for v in quality)})"
                for s in solvers
            ],
        )
        ax.set_ylabel("Độ dài tìm được / tối ưu (log)")
        ax.set_title("Tập chuẩn - mỗi điểm là một màn", fontsize=9)
        ax.set_yscale("log")
        ax.set_ylim(0.8, max(1.3, max((v["ratio"] for v in quality), default=1) * 1.2))
        number_axes(ax)
        ax.yaxis.set_minor_formatter(NullFormatter())
        if quality and all(v["ratio"] == 1 for v in quality):
            ax.text(
                0.5,
                0.88,
                "Tất cả lời giải quan sát đều có tỷ số 1",
                ha="center",
                transform=ax.transAxes,
                fontsize=8,
            )
        save(
            fig,
            "03-chat-luong",
            "Chất lượng lời giải trên tập chuẩn. Mỗi điểm là một màn; "
            "đường ngang ở tỷ số 1 biểu thị lời giải tối ưu. Trục tung dùng log để đọc được cả "
            "tỷ số gần 1 lẫn các lời giải dài hơn nhiều lần. Không dùng đường chứng kiến làm nghiệm tối ưu.",
            quality,
        )

        bounds = []
        for identity, record in records.items():
            if record.get("cohort") == "challenge":
                cert = record["certificate"]
                observed = [v["length"] for (i, _), v in samples.items() if i == identity]
                bounds.append(
                    {
                        "id": identity,
                        "lower": cert["lower_bound"],
                        "witness": len(record["witness"]),
                        "best_observed": min(observed) if observed else None,
                    }
                )
        bounds.sort(key=lambda r: (r["witness"], r["id"]))
        fig, ax = figure(height=max(65, min(150, 30 + 4 * len(bounds))))
        for index, bound in enumerate(bounds):
            bound["label"] = f"M{index + 1:02}"
            ax.plot(
                [bound["lower"], bound["witness"]], [index, index], color="black", linewidth=0.8
            )
            ax.plot(bound["lower"], index, "|", color="black", markersize=5)
            ax.plot(bound["witness"], index, "s", color="black", markersize=3, fillstyle="none")
            if bound["best_observed"] is not None:
                ax.plot(bound["best_observed"], index, "o", color=COLORS[0], markersize=3)
        ax.set_yticks(range(len(bounds)), [f"M{i + 1:02}" for i in range(len(bounds))])
        ax.set_xlabel("Số hành động")
        ax.set_xlim(left=0)
        if not bounds:
            ax.text(
                0.5, 0.5, "Chưa có màn thuộc tập thử thách", ha="center", transform=ax.transAxes
            )
        save(
            fig,
            "04-khoang-nghiem",
            "Khoảng nghiệm của tập thử thách. Vạch: cận dưới; ô vuông: "
            "đường chứng kiến; chấm: lời giải ngắn nhất quan sát được trong thí nghiệm. "
            "CSV ánh xạ M01, M02... sang ID màn. Không khẳng định nghiệm quan sát là tối ưu.",
            bounds,
        )

        fig, axes = figure(height=95, ncols=2, width_ratios=[1.3, 1])
        eligible = [r for r in manifest["records"] if r.get("bridges", 0) > 0]
        eligible.sort(key=lambda r: (r.get("bridges", 0), r["id"]))
        representative = eligible[len(eligible) // 2] if eligible else None
        connections = []
        if representative:
            data = json.loads((corpus / representative["file"]).read_text())
            grid = data["grid"]
            ax = axes[0]
            for r, row in enumerate(grid):
                for c, tile in enumerate(row):
                    if tile != "#":
                        ax.add_patch(
                            Rectangle(
                                (c - 0.5, r - 0.5),
                                1,
                                1,
                                facecolor=".9" if tile == "F" else "white",
                                edgecolor=".65",
                                linewidth=0.25,
                                hatch=".." if tile == "F" else None,
                            )
                        )
                    if tile in "SG":
                        ax.text(c, r, tile, ha="center", va="center", fontsize=8)
            for bi, bridge in enumerate(data["bridges"]):
                for r, c in bridge["cells"]:
                    ax.add_patch(
                        Rectangle(
                            (c - 0.5, r - 0.5),
                            1,
                            1,
                            fill=False,
                            hatch="///",
                            edgecolor="black",
                            linewidth=0.5,
                        )
                    )
                r, c = bridge["cells"][0]
                ax.text(c, r - 0.6, f"B{bi + 1}", ha="center", fontsize=7, color=COLORS[0])
            for si, switch in enumerate(data["switches"]):
                r, c = switch["position"]
                ax.text(c + 0.3, r - 0.35, f"S{si + 1}", fontsize=7, color=COLORS[0])
                ax.plot(
                    c,
                    r,
                    marker="^" if switch["type"] == "split" else "o",
                    color="black",
                    markersize=2,
                )
            ax.set(xlim=(-1, len(grid[0])), ylim=(len(grid), -1), aspect="equal")
            ax.set_xticks([])
            ax.set_yticks([])
            ax.set_anchor("N")
            ax.set_axis_off()
            ax = axes[1]
            bs, ss = data["bridges"], data["switches"]
            ax.set(xlim=(-0.2, 1.2), ylim=(-0.08, 1.08))
            positions = {}
            for side, items in ((0, ss), (1, bs)):
                for index, item in enumerate(items):
                    y = 1 - (index + 0.5) / len(items)
                    positions[item["id"]] = (side, y)
                    ax.add_patch(
                        Circle(
                            (side, y),
                            0.035,
                            facecolor="white",
                            edgecolor="black",
                            linewidth=0.5,
                            zorder=3,
                        )
                    )
                    ax.text(
                        side + (-0.07 if side == 0 else 0.07),
                        y,
                        f"{'S' if side == 0 else 'B'}{index + 1}",
                        ha="right" if side == 0 else "left",
                        va="center",
                        fontsize=8,
                    )
            for switch in ss:
                effect = switch.get("bridge_effect")
                if not effect:
                    continue
                for target in effect["targets"]:
                    ax.annotate(
                        "",
                        xy=positions[target],
                        xytext=positions[switch["id"]],
                        arrowprops={
                            "arrowstyle": "->",
                            "linewidth": 0.6,
                            "linestyle": "--" if effect["mode"] == "toggle" else "-",
                            "shrinkA": 5,
                            "shrinkB": 5,
                        },
                    )
                    start, end = positions[switch["id"]], positions[target]
                    ax.text(
                        0.5,
                        (start[1] + end[1]) / 2 + 0.04,
                        "Đảo trạng thái" if effect["mode"] == "toggle" else "Gán trạng thái",
                        ha="center",
                        fontsize=7,
                    )
                    connections.append(
                        {
                            "map_id": representative["id"],
                            "switch": switch["id"],
                            "bridge": target,
                            "mode": effect["mode"],
                        }
                    )
            ax.axis("off")
        else:
            for ax in axes:
                ax.text(0.5, 0.5, "Không có màn có cầu", ha="center", transform=ax.transAxes)
        axes[0].set_title("(a) Vị trí trên màn chơi", fontsize=9)
        axes[1].set_title("(b) Công tắc tác động lên cầu", fontsize=9)
        fig.supxlabel("S: bắt đầu; G: đích; S1…: công tắc; B1…: cầu; gạch chéo: ô cầu", fontsize=7)
        save(
            fig,
            "06-co-che",
            "Màn chơi và liên kết cơ chế tiêu biểu. (a) S: bắt đầu, G: đích; "
            "gạch chéo: cầu, chấm nền: ô dễ vỡ, tròn: công tắc, tam giác: tách khối. "
            "(b) Số S/B theo thứ tự khai báo trong JSON; mũi tên thể hiện tác động công tắc lên cầu, "
            "nét đứt: toggle, nét liền: set. Đây là liên kết tác động, không phải bằng chứng mọi liên kết đều bắt buộc.",
            connections,
        )

        telemetry = results.parent / "resources.jsonl"
        resources = (
            [json.loads(s) for s in telemetry.read_text().splitlines()]
            if telemetry.exists()
            else []
        )
        fig, axes = figure(height=65, ncols=3)
        if resources:
            times = [(r["time"] - resources[0]["time"]) / 60 for r in resources]
            axes[0].plot(times, [r["system_cpu_percent"] for r in resources], color="black")
            axes[1].plot(
                times, [r["available_memory_bytes"] / 1024**3 for r in resources], color="black"
            )
            axes[2].step(times, [r["accepted"] for r in resources], where="post", color="black")
        else:
            for ax in axes:
                ax.text(0.5, 0.5, "Không thu thập", ha="center", transform=ax.transAxes)
        for ax, letter, ylabel in zip(
            axes, "abc", ["CPU hệ thống (%)", "RAM khả dụng (GiB)", "Màn được nhận"], strict=True
        ):
            panel(ax, letter)
            ax.set(xlabel="Thời gian (phút)", ylabel=ylabel)
            ax.set_ylim(bottom=0)
        save(
            fig,
            "07-tai-nguyen",
            "Tài nguyên và tiến độ pha sinh. CPU là mức bận toàn hệ thống, "
            "RAM là bộ nhớ còn khả dụng; không suy diễn đây là mức dùng riêng của pipeline. "
            "Worker sinh đã dừng trước pha đo solver.",
            resources,
        )
    guide = overview(manifest, meta, records, rows, samples, common, names)
    guide += captions
    guide += ["", "## Phần không xuất và lý do", ""]
    guide += [f"- `{item['name']}`: {item['reason']}" for item in skipped] or [
        "Không có phần bị bỏ."
    ]
    guide += [
        "",
        "## Giới hạn khi diễn giải",
        "",
        "Các kết quả chỉ áp dụng cho corpus, phân tập, cấu hình và máy đã đo. "
        "Tập chuẩn ưu tiên màn có thể chứng nhận trong ngân sách trạng thái; "
        "không đại diện mọi màn Bloxorz hoặc độ khó với con người. "
        "Màn vô nghiệm không tham gia tỷ lệ giải hay tập chi phí thành công; "
        "trạng thái của chúng vẫn được giữ trong data/all-runs.csv.",
        "",
    ]
    (output / "captions.md").write_text("\n".join(guide), encoding="utf-8")
    # Remove only known generated artifacts no longer part of this export.
    for name in FIGURE_NAMES - {item["name"] for item in outputs}:
        for extension in ("pdf", "svg", "png"):
            (output / f"{name}.{extension}").unlink(missing_ok=True)
        (output / "data" / f"{name}.csv").unlink(missing_ok=True)
    (output / "figure-manifest.json").write_text(
        json.dumps(
            {
                "schema_version": 2,
                "font": str(font),
                "font_family": "Times New Roman",
                "dpi": 600,
                "corpus_hash": manifest["corpus_hash"],
                "source_corpus": str(corpus),
                "source_results": str(results),
                "figures": outputs,
                "skipped": skipped,
                "selected_maps": len(records),
                "common_success_maps": len(common),
                "status_counts": dict(Counter(r["status"] for r in rows)),
                "planned_runs": len(rows),
                "not_run": sum(r["status"] == "not_run" for r in rows),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    table(output / "data" / "all-runs.csv", rows)
    print(f"Exported {len(outputs)} figures with Times New Roman: {output}")
