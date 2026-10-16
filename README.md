# Bloxorz

Game desktop Python + PySide6 cho **CSC14003 — Project 1**. Bản hiện tại triển khai chơi thủ công và toàn bộ cơ chế nâng cao; thuật toán tìm kiếm sẽ được bổ sung sau.

## Tải và chạy game

Cần **Python 3.11 trở lên**, kết nối Internet để cài dependencies và một phiên desktop có màn hình. Git chỉ cần nếu chọn cách clone. Game đã có sẵn **10 stage**, không cần tải thêm asset hay tạo bản đồ.

### 1. Tải mã nguồn

**Dùng Git:** trên trang repository, chọn **Code → HTTPS** và copy URL. Thay `URL_REPOSITORY` bên dưới bằng URL vừa copy:

```bash
git clone URL_REPOSITORY Bloxorz
cd Bloxorz
```

**Hoặc tải ZIP:** chọn **Code → Download ZIP**, giải nén rồi mở terminal trong thư mục chứa `main.py`, `pyproject.toml` và `requirements.txt`.

Tất cả lệnh tiếp theo đều chạy từ thư mục này. Chọn hướng dẫn đúng hệ điều hành; mỗi máy tự tạo môi trường **`.venv-game`**, không sao chép venv của người khác. Các lệnh gọi trực tiếp Python trong venv nên không cần activate.

### 2. Cài dependencies và mở game

**Linux / macOS:**

```bash
python3 --version
python3 -m venv .venv-game
.venv-game/bin/python -m pip install -r requirements.txt
.venv-game/bin/python main.py
```

**Windows — PowerShell:**

```powershell
py -3 --version
py -3 -m venv .venv-game
.\.venv-game\Scripts\python.exe -m pip install -r requirements.txt
.\.venv-game\Scripts\python.exe main.py
```

Kiểm tra phiên bản in ra từ lệnh đầu tiên phải từ 3.11 trở lên. Nếu Windows không có lệnh `py` nhưng đã có `python`, thay `py -3` bằng `python` trong hai lệnh đầu.

`requirements.txt` cài project hiện tại và PySide6; chỉ chơi game thì không cần pytest/Ruff. Khi cài xong, cửa sổ **Bloxorz — Manual play** sẽ mở ở stage 01. Có thể thử thắng màn đầu bằng 4 lần bấm **→**, chờ khối lăn xong giữa các lần bấm. Chọn stage khác rồi bấm **New game** để chơi tiếp.

### 3. Chạy lại ở những lần sau

Mở terminal tại thư mục dự án và chạy lệnh tương ứng; không cần tạo lại venv hoặc cài lại dependencies mỗi lần:

| Hệ điều hành | Lệnh |
| --- | --- |
| Linux / macOS | `.venv-game/bin/python main.py` |
| Windows PowerShell | `.\.venv-game\Scripts\python.exe main.py` |

Cũng có thể thay `main.py` bằng `-m bloxorz`. Nếu tải lại dự án sang thư mục mới, hãy tạo venv và cài dependencies lại tại đó.

### Lỗi thường gặp

| Hiện tượng | Cách xử lý |
| --- | --- |
| Không tìm thấy `python3`, `py` hoặc `python` | Cài Python 3.11+ và mở lại terminal; kiểm tra phiên bản trước khi tạo venv. |
| Thiếu `venv` / `ensurepip` trên Linux | Cài thành phần venv tương ứng với Python đang dùng. Với Python mặc định từ Ubuntu/Debian, thường là gói `python3-venv`, rồi tạo lại môi trường. |
| Không tìm thấy `main.py` / `requirements.txt` | Chuyển terminal vào thư mục dự án đã clone hoặc giải nén. |
| `ModuleNotFoundError: bloxorz` hoặc `PySide6` | Chạy lại lệnh cài `requirements.txt` và dùng đúng executable Python trong `.venv-game` như hướng dẫn trên. |
| Qt báo lỗi `xcb` / platform plugin trên Linux | Kiểm tra các thư viện hệ thống Qt và phiên desktop X11/Wayland theo [hướng dẫn Qt for Python](https://doc.qt.io/qtforpython-6/gettingstarted.html). |
| Chạy nhưng không thấy cửa sổ | Chạy trong phiên desktop; bỏ cấu hình `QT_QPA_PLATFORM=offscreen` nếu đã đặt để test. Offscreen chỉ phục vụ kiểm thử. |

Nếu còn lỗi, gửi nhóm **hệ điều hành, phiên bản Python, lệnh đã chạy và toàn bộ thông báo lỗi** để dễ kiểm tra.

## Điều khiển

| Thao tác | Phím / nút |
| --- | --- |
| Lăn khối hoặc di chuyển cube đang chọn | Mũi tên / WASD / các nút hướng |
| Đổi cube sau khi tách | Space / Switch cube |
| Chơi lại màn hiện tại | R / Restart |
| Bắt đầu màn đã chọn | Chọn Stage rồi nhấn New game |
| Chuyển màn sau khi thắng | Next stage |
| Nạp màn tùy chỉnh | Open level file… |

Nhấp vào bàn cờ nếu muốn đưa focus bàn phím trở lại game. Khi chọn Stage, màn đang chơi giữ nguyên cho đến khi nhấn **New game**. Các nút di chuyển tự đưa focus về bàn cờ sau khi nhấn.

- Chỉ khối nguyên vẹn **đứng trên G** mới thắng; nằm ngang qua G hoặc đặt cube đơn lên G không thắng.
- Rơi ra ngoài, đứng trên fragile hoặc thiếu ô đỡ sẽ **thua**. Nhấn R để chơi lại.
- Fragile màu cam chịu được khối nằm và cube đơn, không chịu khối nguyên vẹn đứng.
- Switch tròn nhận mọi kiểu khối; switch X cần khối nguyên vẹn đứng; switch `( )` tách và teleport khối.
- Bridge mở là ô xanh ngọc đặc; bridge đóng có viền đứt và không đỡ được khối.
- Hai cube tự ghép khi một bước di chuyển đưa chúng về hai ô kề nhau. Viền trắng chỉ cube đang điều khiển.
- Bộ đếm **Rolls** tính cả bước di chuyển cube và nước đi gây thua; **Swaps** đếm riêng thao tác đổi cube. Hành động không hợp lệ không tăng bộ đếm.

## Đồ họa và animation

Bàn cờ dùng phép chiếu nghiêng 2.5D, sàn có độ dày và goal có thành hố. Block màu nâu gỉ pha các mảng xám than, có mặt sáng/tối; texture bám theo mặt block khi xoay.

- Khi di chuyển, khối xoay 90° quanh cạnh tiếp xúc với sàn. Cube đơn cũng lăn; cube không được chọn giữ nguyên vị trí.
- Khi cả khối mất chỗ đỡ, nó rơi tăng tốc xuống vực. Nếu khối nằm chỉ còn một ô được đỡ, nó nghiêng ra ngoài quanh mép ô đó, nhấc phần trên sàn lên, rồi mới rơi tự do và trôi ra ngoài. Hướng nghiêng lấy từ ô bị hụt, không phụ thuộc vào phím vừa bấm.
- Khi hai cube tách rời, chỉ cube mất chỗ đỡ rơi; cube còn được đỡ giữ nguyên vị trí trong hiệu ứng thua. Phần nằm dưới mặt sàn vẫn được che theo vị trí nền.
- Khi thắng, trụ chìm xuống goal; chỉ phần còn ở trên mặt sàn được hiển thị.
- Cầu xoay lên từ phía dưới khi mở, gập xuống khi đóng. Split/rejoin có hiệu ứng chuyển tiếp ngắn.
- Nước đi mới bị bỏ qua trong lúc animation chạy. **Restart**, **New game** và đổi màn hủy hiệu ứng ngay; không phải đợi animation kết thúc.

Animation chạy bằng Qt trên UI thread, không dùng `sleep` và không sửa luật trong engine. Kết quả thắng/thua được hiển thị sau khi hiệu ứng hoàn tất.

Các quyết định chi tiết nằm trong [gameplay conventions](docs/gameplay_conventions.md).

## Các màn đi kèm

| Màn | Kích thước | Thao tác tối thiểu | Cơ chế |
| --- | --- | ---: | --- |
| 01 · First steps | 9 × 5 | 4 | Lăn cơ bản, mục tiêu đứng đúng ô |
| 02 · Light touch | 11 × 6 | 10 | Fragile, đi vòng để đổi hướng |
| 03 · A little pressure | 12 × 7 | 11 | Soft switch, cầu toggle |
| 04 · Full weight | 13 × 8 | 13 | Heavy switch, cầu set-open, fragile |
| 05 · Two halves | 14 × 9 | 20 | Tách khối, điều khiển cả hai cube qua đường gấp khúc rồi ghép |
| 06 · Bridge builders | 16 × 10 | 25 | Cube A mở cầu cho cube B, fragile, ghép ở đảo cuối |
| 07 · Switchyard | 17 × 11 | 26 | Bốn đảo, ba cầu, chuỗi soft/heavy switch |
| 08 · Point of no return | 18 × 12 | 30 | Chuẩn bị cầu đích trước khi switch set-close khóa đường về |
| 09 · Double shift | 20 × 13 | 45 | Hai lần tách/ghép; ghép để bấm heavy rồi tách lần nữa |
| 10 · The long way home | 22 × 14 | 57 | Toàn bộ cơ chế, bốn cầu, hai lần tách/ghép, khóa đường về |

Diện tích có thể đi (tính cả cầu) tăng từ **21 lên 130 ô**. Độ khó tăng qua đường đi dài hơn, hướng tiếp cận switch, phối hợp hai cube và thứ tự mở/đóng cầu. Các con số tối thiểu được kiểm chứng bằng công cụ duyệt trạng thái tạm thời khi thiết kế màn; mỗi lần đổi cube cũng tính là một thao tác.

Chuỗi thắng cố định nằm trong `tests/fixtures/stage_routes.json`. `tests/test_campaign.py` kiểm tra cả 10 màn thắng được, kích hoạt mọi switch, sử dụng mọi cầu và fragile, cùng thứ tự chuẩn bị đường ra và tách/ghép. Game hiện vẫn chỉ hỗ trợ chơi thủ công.

## Level JSON

Các màn được đóng gói trong `src/bloxorz/levels/`. Có thể sao chép một file để tạo màn mới. Ký hiệu: `#` void, `.` floor, `S` start, `G` goal, `F` fragile; mỗi màn có đúng một S và một G. Tọa độ là `[row, column]`, bắt đầu từ 0.

Ví dụ màn nhỏ:

```json
{
  "id": "my_stage",
  "name": "My stage",
  "description": "Roll right twice.",
  "grid": ["S..G"]
}
```

Bridge được định nghĩa trên ô `#`; switch đặt trên ô `.` hoặc S:

```json
{
  "id": "my_bridge",
  "name": "My bridge",
  "grid": ["S...##G"],
  "bridges": [
    {"id": "crossing", "cells": [[0, 4], [0, 5]], "initially_open": false}
  ],
  "switches": [
    {
      "id": "button",
      "type": "soft",
      "position": [0, 1],
      "bridge_effect": {"mode": "toggle", "targets": ["crossing"]}
    }
  ]
}
```

Hiệu ứng permanent dùng `{"mode": "set", "targets": ["crossing"], "open": true}` hoặc `false`. Nó gán trạng thái cầu, không khóa cầu chống lại switch khác. Split switch dùng `"type": "split"` và `"spawn_positions": [[r1, c1], [r2, c2]]`; có thể thêm `bridge_effect` nếu cần.

Nạp qua GUI hoặc truyền đường dẫn khi chạy:

```bash
.venv-game/bin/python -m bloxorz --level path/to/stage.json
```

Loader kiểm tra cấu trúc, vị trí, ID, bridge targets và spawn positions. Loader không yêu cầu màn phải có lời giải.

## Cấu trúc code

```text
src/bloxorz/
  domain/          # Immutable models, pure transition, validation
  application/     # GameSession, trạng thái thắng/thua và counters
  infrastructure/  # JSON loader và packaged resources
  presentation/    # Qt window, projected rendering, rigid motion và input
  levels/          # Mười màn JSON đi kèm
tests/             # Engine, loader, session và GUI integration tests
```

`transition(level, state, action)` trả `TransitionResult` với `next_state`, `outcome`, `events` và `reason`. Outcome gồm `MOVED`, `WON`, `LOST`, `INVALID`. Khi bổ sung search, chỉ mở rộng kết quả `MOVED`/`WON`; các thuật toán không cần tự viết lại luật. `legal_actions()` cũng loại các hành động gây thua.

## Kiểm tra

Phần này dành cho thành viên phát triển. Cài thêm pytest và Ruff vào cùng venv trước khi chạy checks.

**Linux / macOS:**

```bash
.venv-game/bin/python -m pip install -e '.[dev]'
.venv-game/bin/python -m pytest -q
.venv-game/bin/python -m ruff check .
.venv-game/bin/python -m ruff format --check .
.venv-game/bin/python -m pip check
```

**Windows — PowerShell:**

```powershell
.\.venv-game\Scripts\python.exe -m pip install -e ".[dev]"
.\.venv-game\Scripts\python.exe -m pytest -q
.\.venv-game\Scripts\python.exe -m ruff check .
.\.venv-game\Scripts\python.exe -m ruff format --check .
.\.venv-game\Scripts\python.exe -m pip check
```

Tests GUI dùng Qt offscreen, không cần mở cửa sổ. Chúng kiểm tra bàn phím/nút bấm, kết quả thắng/thua, restart, chuyển màn và split/rejoin trên widget thật. Tests animation kiểm tra các frame trung gian, khóa input, hủy hiệu ứng, cầu mở/đóng, clipping tại goal và đồng hồ Qt. Các tests hình học đối chiếu vị trí cuối của 12 kiểu lăn với engine và kiểm tra khối giữ nguyên kích thước giữa chuyển động. Tests engine bao phủ cầu, switch, teleport, support và tính bất biến của state.

Môi trường đã kiểm chứng: Python 3.13.7, PySide6 6.12.0, pytest 9.1.1 và Ruff 0.17.0 trên Linux. Việc kiểm tra hiển thị hiện dùng Qt offscreen; chưa kiểm thử trực tiếp trên Windows/macOS.

## Tài liệu

- Đề bài: `AI_Project_1_Bloxorz_Solver.md` (đang được ignore; nhận riêng từ nhóm nếu bản tải về không có file này).
- [Hướng dẫn interface thuật toán cho thành viên nhóm](docs/plans/search-interface.md)
- [Kiến trúc tổng thể](PROJECT_ARCHITECTURE.md)
- [Kế hoạch triển khai bản chơi thủ công](docs/plans/2026-10-15-manual-game.md)
- [Thiết kế và kiểm chứng 10 stage](docs/plans/2026-10-16-ten-stages.md)
- [Quy ước gameplay](docs/gameplay_conventions.md)
- [QWidget](https://doc.qt.io/qtforpython-6/PySide6/QtWidgets/QWidget.html), [QPainter](https://doc.qt.io/qtforpython-6/PySide6/QtGui/QPainter.html), [QTest](https://doc.qt.io/qtforpython-6/PySide6/QtTest/QTest.html)
