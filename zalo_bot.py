import time
import random
import os
import json 
import datetime 
import requests 
import threading
import queue
import traceback
import base64
import re
import concurrent.futures
from collections import OrderedDict
from bs4 import BeautifulSoup 
from lunarcalendar import Converter, Solar 
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.chrome.service import Service
from selenium.common.exceptions import TimeoutException
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager
import uuid
from PIL import Image, ImageDraw, ImageFont, ImageFilter
from io import BytesIO 

# ==============================================================================
# 👇 CẤU HÌNH BOT & BỘ LƯU TRỮ
# ==============================================================================

TEN_NHOM_CHAT = "Nà ná na na" 
PREFIX = "/" 
DATA_FILE = "thong_ke_chat.json" 
CONFIG_FILE = "bot_config.json" 
TAROT_FILE = "tarot_data.json" 
COIN_FILE = "coin_data.json" 
LOAN_FILE = "loan_data.json" 
CREDIT_FILE = "credit_data.json" 
JOBS_FILE = "jobs_data.json" 
STREAKS_FILE = "streaks_data.json" 
ALTP_FILE = "altp_questions.json" 
BUSINESS_FILE = "business_config.json" 
ASSETS_FILE = "assets_data.json" 
P2P_FILE = "p2p_data.json" 
GOLD_FILE = "gold_data.json" 
ALTP_WINNERS_FILE = "altp_winners.json" 
PROFILE_FILE = "profile_data.json"
AVATAR_FILE = "avatar_data.json" 
INVENTORY_FILE = "inventory_data.json"
MARKET_FILE = "market_data.json"

# Cấu hình giới hạn nhân viên và tiêu hao vật liệu theo Quy mô
MAX_EMP = {1: 2, 2: 4, 3: 7, 4: 10}
MAT_USAGE = {1: 15, 2: 25, 3: 35, 4: 50}
MAT_NAMES = {"th": "📦 Hàng hóa", "qa": "🥩 Thực phẩm", "xd": "🧱 Vật liệu", "nh": "💰 Quỹ dự trữ"}
GOLD_RATE_DIVISOR = 100 
BOT_NAME = "Tẻn"               # Tên bot trong coin_data
BOT_DEFAULT_BALANCE = 10_000_000_000  # Số dư mặc định: 10 tỷ xu

# ==============================================================================
# 🖼️ CACHE AVATAR - LRU có giới hạn 60 entry, tránh RAM phình vô hạn
# ==============================================================================
avatar_cache = OrderedDict()   # Lưu avatar đã tải: {cache_key: PIL.Image}
_AVATAR_CACHE_MAX = 60          # Tối đa 60 entry (~30-60 MB), sau đó xóa entry cũ nhất

def _avatar_cache_put(key, img):
    """Thêm vào cache, evict entry cũ nhất nếu vượt giới hạn."""
    avatar_cache[key] = img
    if len(avatar_cache) > _AVATAR_CACHE_MAX:
        avatar_cache.popitem(last=False)  # Xóa entry cũ nhất (FIFO/LRU)

# ==============================================================================
# 🔤 CACHE FONT (Load 1 lần lúc khởi động, dùng mãi - hỗ trợ Linux Mint / Windows)
# ==============================================================================
_font_cache = {}  # {size: ImageFont}

def get_font(size):
    """Lấy font từ cache theo size, hỗ trợ Linux Mint (Liberation/DejaVu/Noto) & Windows."""
    if size not in _font_cache:
        font_obj = None
        font_candidates = [
            "font.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            "/usr/share/fonts/truetype/noto/NotoSans-Regular.ttf",
            "/usr/share/fonts/truetype/freefont/FreeSans.ttf",
            "arial.ttf",
            "segoeui.ttf",
            "calibri.ttf"
        ]
        for font_name in font_candidates:
            try:
                font_obj = ImageFont.truetype(font_name, size)
                break
            except Exception:
                pass
        if not font_obj:
            try:
                font_obj = ImageFont.load_default(size=size)
            except Exception:
                font_obj = ImageFont.load_default()
        _font_cache[size] = font_obj
    return _font_cache[size]

def init_font_cache():
    """Load trước tất cả font sizes được dùng trong bot."""
    sizes = [24, 25, 26, 28, 30, 32, 35, 36, 40, 45, 48, 55, 56, 60, 64, 65, 70, 72]
    for s in sizes:
        get_font(s)
    print(f"✅ Đã cache {len(_font_cache)} font sizes vào RAM.")

# ==============================================================================
# 📦 CACHE INVENTORY (Dùng chung 1 dict RAM thay vì load DB mỗi lệnh)
# ==============================================================================
_inventory_cache = None  # None = chưa load, {} = đã load nhưng rỗng

def get_inventory_data():
    """Lấy inventory từ cache RAM, load từ DB nếu chưa có."""
    global _inventory_cache
    if _inventory_cache is None:
        _inventory_cache = load_json_data(INVENTORY_FILE, {})
    return _inventory_cache

def save_inventory_data():
    """Lưu inventory từ RAM vào DB."""
    global _inventory_cache
    if _inventory_cache is not None:
        save_json_data(INVENTORY_FILE, _inventory_cache)

# ==============================================================================
# 📊 CACHE DAILY BUSINESS STATS (Tương tự inventory — load 1 lần, flush async)
# ==============================================================================
DAILY_STATS_FILE = "daily_business_stats.json"
_daily_stats_cache = None
_daily_stats_dirty = False

def get_daily_stats():
    """Lấy daily stats từ RAM cache."""
    global _daily_stats_cache
    if _daily_stats_cache is None:
        _daily_stats_cache = load_json_data(DAILY_STATS_FILE, {})
    return _daily_stats_cache

def mark_daily_stats_dirty():
    global _daily_stats_dirty
    _daily_stats_dirty = True

def flush_daily_stats_if_dirty():
    global _daily_stats_dirty, _daily_stats_cache
    if _daily_stats_dirty and _daily_stats_cache is not None:
        save_json_data(DAILY_STATS_FILE, _daily_stats_cache)
        _daily_stats_dirty = False

def reset_daily_stats():
    global _daily_stats_cache, _daily_stats_dirty
    _daily_stats_cache = {}
    _daily_stats_dirty = True

# ==============================================================================
# ⚡ ASYNC DB WRITE QUEUE (ghi DB không block vòng lặp chính)
# ==============================================================================
_db_write_queue = queue.Queue()

def async_save(filepath, data):
    """Đưa lệnh ghi vào queue thay vì ghi trực tiếp - không block main thread."""
    _db_write_queue.put((filepath, data))

def _db_writer_thread():
    """Thread nền xử lý queue ghi DB liên tục."""
    while True:
        try:
            filepath, data = _db_write_queue.get(timeout=1)
            save_json_data(filepath, data)
        except queue.Empty:
            # Flush các dirty cache định kỳ khi queue trống
            flush_daily_stats_if_dirty()
        except Exception as e:
            print(f"⚠️ [DB Writer] Lỗi ghi {e}")

def get_cached_avatar(avatar_url, size=(80, 80), circle=False):
    """Lấy avatar từ cache LRU, nếu chưa có thì tải và lưu vào cache."""
    if not avatar_url:
        return None
    
    cache_key = f"{avatar_url}_{size}"
    if cache_key in avatar_cache:
        return avatar_cache[cache_key].copy()
    
    try:
        res = requests.get(avatar_url, timeout=5)
        avt = Image.open(BytesIO(res.content)).convert("RGBA")
        avt = avt.resize(size, Image.LANCZOS)
        
        if circle:
            mask = Image.new('L', size, 0)
            ImageDraw.Draw(mask).ellipse((0, 0, size[0], size[1]), fill=255)
            avt.putalpha(mask)
        
        _avatar_cache_put(cache_key, avt)  # Dùng LRU put thay vì dict trực tiếp
        return avt.copy()
    except:
        return None


# 🏊 BOUNDED THREAD POOL cho avatar preload — tránh spawn thread mới mỗi lần
# max_workers=2 phù hợp VPS 2 core, không tranh CPU với main loop
_avatar_preload_pool = concurrent.futures.ThreadPoolExecutor(max_workers=2, thread_name_prefix="avt_preload")

def preload_avatar_async(avatar_url):
    """Tải avatar ngầm qua bounded pool thay vì spawn thread mới mỗi lần."""
    if not avatar_url:
        return
    # Kiểm tra trực tiếp bằng any() thay vì tạo list mới mỗi lần
    if any(k.startswith(avatar_url) for k in avatar_cache):
        return
    try:
        _avatar_preload_pool.submit(get_cached_avatar, avatar_url)
    except Exception:
        pass  # Pool đã shutdown hoặc full — bỏ qua, không critical


# 🖼️ DEDICATED THREAD POOL cho PIL image rendering — offload khỏi main thread
# max_workers=1 vì render ảnh tốn RAM, tuần tự hoá tránh spike bộ nhớ
_pil_render_pool = concurrent.futures.ThreadPoolExecutor(max_workers=1, thread_name_prefix="pil_render")

def render_image_async(render_fn, *args, **kwargs):
    """Chạy hàm render PIL trong pool, trả về Future. Gọi .result() khi cần kết quả."""
    return _pil_render_pool.submit(render_fn, *args, **kwargs)

admin_cmd_queue = queue.Queue()
global_xd_mode = 2 # 1: Dễ, 2: Thường, 3: Khó
STARTUP_MESSAGES = [
    ""
]

LOSE_MESSAGES = [
    "Còn cái nịt nha con trai! 🩲", "Cờ bạc người không chơi là người thắng, mà ông chơi thì ông ngu rồi! 🤡",
    "Về nhà cắm sổ đỏ ra đây chơi tiếp đi, Tẻn chờ! 🏠", "Thua keo này ta bày keo khác... à mà làm gì còn tiền mà bày! 💸",
    "Gà vãi chưởng, đánh thế này bao giờ mới giàu? 🐔", "Nhà cái đến từ châu Âu xin chân thành cảm ơn nhà tài trợ! 🤑",
    "Đúng là tấm chiếu mới, để Tẻn dạy cho bài học! 🛏️", "Khóc đi, khóc to lên! 😭",
    "Trình độ này thì đi nhặt ve chai còn không đủ sống! 🗑️", "Cảm ơn vì đã quyên góp từ thiện cho quỹ người nghèo! 💰",
    "Mẹ dặn cờ bạc là bác thằng bần, không nghe thì giờ đi móc bọc nhé! 🛍️", "Cười ẻ, đánh đâu trượt đó! 😂"
]

WIN_MESSAGES = [
    "Ăn rùa thôi con trai, chốc nữa nôn ra trả nhà cái mau! 🐢", "Đỏ thôi, đen quên đi! Lát Tẻn lột lại hết! 🤬",
    "Nay cúng cô hồn hay sao mà hên thế? 👻", "Tẻn ghi sổ rồi đấy, thắng được của nhà cái không dễ nuốt đâu! 📓",
    "Nhân phẩm bùng nổ à? Coi chừng lát ra đường dẫm trúng ... 💩", "Húp được miếng tiền mà cười đến mang tai rồi kìa! 🐸",
    "Chơi bịp đúng không? Gọi công an gõ đầu giờ! 🚓", "Thắng thì mua trà sữa cho anh em đi, ki bo là nghiệp quật đấy! 🧋",
    "Hay lắm, tiếp tục nuôi mộng làm giàu từ cờ bạc đi! 🤡", "Thắng xíu thôi làm gì căng, tí Tẻn luộc lại cái một! ✂️"
]

ALTP_LOSE_MESSAGES = [
    "Kiến thức đi vào lòng đất! Về học lại mẫu giáo đi bạn ơi! 📉", "MC xin phép cạn lời với câu trả lời này... 🎤",
    "Có thế cũng sai, trả lại bằng tốt nghiệp cho cô giáo đi! 🎓", "Khán giả trường quay đang cười bạn kìa, nhục chưa! 🤦",
    "Ai làm triệu phú thì làm, chứ bạn thì làm vô sản nhé! 🗑️", "Tổ tư vấn tại chỗ xin từ chối hiểu ca này! 🙅",
    "Câu này nhắm mắt cũng chọn đúng, thế mà bạn lại... 🤡", "Chưa kịp nóng ghế đã bị đuổi về, tiếc quá nha! 💨"
]

# ==============================================================================
# 🔮 78 LÁ BÀI TAROT ĐẦY ĐỦ (22 Major + 56 Minor Arcana)
# Mỗi lá: {"name": "Tên tiếng Anh", "viet": "Tên tiếng Việt", "img": "TenFile-Tarot.jpg", "mean": "Ý nghĩa"}
# ==============================================================================
# ==============================================================================
# 🔮 78 LÁ BÀI TAROT ĐẦY ĐỦ (22 Major + 56 Minor Arcana)
# Mỗi lá: {"name": "Tên tiếng Anh", "viet": "Tên tiếng Việt", "img": "TenFile-Tarot.jpg", "mean": "Ý nghĩa"}
# ==============================================================================
TAROT_CARDS_78 = [
    # ─── MAJOR ARCANA (0–21) ─────────────────────────────────────────────────
    {"name": "The Fool",          "viet": "Kẻ Khờ",            "img": "Fool-Tarot.jpg",             "mean": "Bắt đầu hành trình mới, ngây thơ, liều lĩnh, tự do. Cứ bước tới đi, vũ trụ sẽ lo phần còn lại!"},
    {"name": "The Magician",      "viet": "Ảo Thuật Gia",       "img": "Magician-Tarot.jpg",         "mean": "Tài năng, ý chí, hành động. Bạn có đủ đồ nghề để biến ý tưởng thành hiện thực."},
    {"name": "The High Priestess","viet": "Nữ Tư Tế",           "img": "High-Priestess-Tarot.jpg",   "mean": "Trực giác, bí ẩn, nội tâm. Hãy tin vào linh cảm của chính mình hơn bất kỳ ai."},
    {"name": "The Empress",       "viet": "Nữ Hoàng",           "img": "Empress-Tarot.jpg",          "mean": "Trù phú, sáng tạo, tình mẫu tử. Thời điểm tốt để vun đắp các mối quan hệ và tận hưởng cuộc sống."},
    {"name": "The Emperor",       "viet": "Hoàng Đế",           "img": "Emperor-Tarot.jpg",          "mean": "Kỷ luật, quyền lực, lý trí. Hãy giữ cái đầu lạnh và kiểm soát mọi thứ xung quanh."},
    {"name": "The Hierophant",    "viet": "Giáo Hoàng",         "img": "Hierophant-Tarot.jpg",       "mean": "Truyền thống, tín ngưỡng, sự hướng dẫn. Làm theo lề lối, đừng đi đường tắt."},
    {"name": "The Lovers",        "viet": "Đôi Tình Nhân",      "img": "Lovers-Tarot.jpg",           "mean": "Tình yêu, lựa chọn, hòa hợp. Một quyết định quan trọng cần được đưa ra bằng con tim."},
    {"name": "The Chariot",       "viet": "Cỗ Chiến Xa",        "img": "Chariot-Tarot.jpg",          "mean": "Kiểm soát, ý chí, chiến thắng. Hãy tiến thẳng về phía trước, không lùi bước."},
    {"name": "Strength",          "viet": "Sức Mạnh",           "img": "Strength-Tarot.jpg",         "mean": "Dũng cảm, kiên nhẫn, điều khiển bản năng. Lấy nhu thắng cương, dùng sự bình tĩnh để chinh phục."},
    {"name": "The Hermit",        "viet": "Ẩn Sĩ",              "img": "Hermit-Tarot.jpg",           "mean": "Cô độc, chiêm nghiệm, tìm kiếm nội tâm. Hợp để tĩnh tâm, tránh xa chỗ ồn ào thị phi."},
    {"name": "Wheel of Fortune",  "viet": "Bánh Xe Vận Mệnh",   "img": "Wheel-of-Fortune-Tarot.jpg", "mean": "Vận may, thay đổi, chu kỳ nghiệp quả. Thời tới cản không kịp — hoặc là quay xe bất ngờ!"},
    {"name": "Justice",           "viet": "Công Lý",            "img": "Justice-Tarot.jpg",          "mean": "Công bằng, nhân quả, sự thật. Gieo nhân nào gặt quả nấy, hãy hành xử quang minh."},
    {"name": "The Hanged Man",    "viet": "Người Treo Ngược",   "img": "Hanged-Man-Tarot.jpg",       "mean": "Hy sinh, buông bỏ, góc nhìn mới. Đang bế tắc thì thử lật ngược vấn đề lại xem sao."},
    {"name": "Death",             "viet": "Cái Chết",           "img": "Death-Tarot.jpg",            "mean": "Kết thúc, chuyển hóa, tái sinh. Đừng sợ, một chương cũ đóng lại để cái mới xịn hơn mở ra."},
    {"name": "Temperance",        "viet": "Điều Độ",            "img": "Temperance-Tarot.jpg",       "mean": "Cân bằng, hòa hợp, kiên nhẫn. Đừng thái quá, mọi việc cứ vừa phải thì mới êm đẹp."},
    {"name": "The Devil",         "viet": "Ác Quỷ",             "img": "Devil-Tarot.jpg",            "mean": "Cám dỗ, xiềng xích, u mê vật chất. Cẩn thận bị cuốn vào những thứ độc hại hoặc tốn tiền vô ích!"},
    {"name": "The Tower",         "viet": "Tòa Tháp Sụp Đổ",   "img": "Tower-Tarot.jpg",            "mean": "Biến cố bất ngờ, sụp đổ, giải thoát. Có biến! Nhưng nó giúp đập đi xây lại thứ tốt hơn."},
    {"name": "The Star",          "viet": "Ngôi Sao",           "img": "Star-Tarot.jpg",             "mean": "Hy vọng, niềm tin, bình yên. Mọi giông bão đã qua, ánh sáng đang chờ ở phía trước."},
    {"name": "The Moon",          "viet": "Mặt Trăng",          "img": "Moon-Tarot.jpg",             "mean": "Ảo ảnh, lo âu, tiềm thức. Cẩn thận bị lừa dối hoặc tự suy diễn lung tung."},
    {"name": "The Sun",           "viet": "Mặt Trời",           "img": "Sun-Tarot.jpg",              "mean": "Thành công, rạng rỡ, niềm vui. Một ngày chói lóa, làm gì cũng thuận lợi!"},
    {"name": "Judgement",         "viet": "Phán Xét",           "img": "Judgement-Tarot.jpg",        "mean": "Tái sinh, thức tỉnh, đánh giá lại. Đã đến lúc nhìn nhận bản thân và bước sang trang mới."},
    {"name": "The World",         "viet": "Thế Giới",           "img": "World-Tarot.jpg",            "mean": "Hoàn thành, viên mãn, thành tựu trọn vẹn. Mọi thứ đều đạt đến đỉnh cao, chúc mừng!"},
    
    # ─── MINOR ARCANA – WANDS (Gậy / Lửa) ─────────────────────────────────
    {"name": "Ace of Wands",      "viet": "Át Gậy",             "img": "Ace-of-Wands-Tarot.jpg",    "mean": "Khởi đầu mới đầy nhiệt huyết, cảm hứng bùng cháy, cơ hội sáng tạo."},
    {"name": "Two of Wands",      "viet": "Hai Gậy",            "img": "Two-of-Wands-Tarot.jpg",    "mean": "Lập kế hoạch, mở rộng tầm nhìn, đứng trước ngã rẽ quan trọng."},
    {"name": "Three of Wands",    "viet": "Ba Gậy",             "img": "Three-of-Wands-Tarot.jpg",  "mean": "Mở rộng tầm với, chờ đợi kết quả, những kế hoạch đang thành hình."},
    {"name": "Four of Wands",     "viet": "Bốn Gậy",            "img": "Four-of-Wands-Tarot.jpg",   "mean": "Lễ kỷ niệm, hạnh phúc, nền tảng vững chắc. Thời điểm để ăn mừng!"},
    {"name": "Five of Wands",     "viet": "Năm Gậy",            "img": "Five-of-Wands-Tarot.jpg",   "mean": "Cạnh tranh, xung đột nhỏ, thử thách. Hãy biến áp lực thành động lực."},
    {"name": "Six of Wands",      "viet": "Sáu Gậy",            "img": "Six-of-Wands-Tarot.jpg",    "mean": "Chiến thắng, được công nhận, lãnh đạo. Nỗ lực đã được đền đáp xứng đáng."},
    {"name": "Seven of Wands",    "viet": "Bảy Gậy",            "img": "Seven-of-Wands-Tarot.jpg",  "mean": "Bảo vệ lập trường, kiên trì trước áp lực, không lùi bước."},
    {"name": "Eight of Wands",    "viet": "Tám Gậy",            "img": "Eight-of-Wands-Tarot.jpg",  "mean": "Tốc độ, hành động nhanh, tin tức đến, mọi thứ đang chuyển động."},
    {"name": "Nine of Wands",     "viet": "Chín Gậy",           "img": "Nine-of-Wands-Tarot.jpg",   "mean": "Kiên cường, phòng thủ, gần đến đích rồi — đừng bỏ cuộc lúc này!"},
    {"name": "Ten of Wands",      "viet": "Mười Gậy",           "img": "Ten-of-Wands-Tarot.jpg",    "mean": "Gánh nặng, trách nhiệm quá tải. Hãy học cách ủy quyền và buông bớt."},
    {"name": "Page of Wands",     "viet": "Tiểu Thư Gậy",       "img": "Page-of-Wands-Tarot.jpg",   "mean": "Nhiệt tình, tò mò, thông điệp mới. Tinh thần khám phá đang rực cháy."},
    {"name": "Knight of Wands",   "viet": "Hiệp Sĩ Gậy",        "img": "Knight-of-Wands-Tarot.jpg", "mean": "Đam mê, táo bạo, hành động bốc đồng. Hãy kiềm chế và chọn đúng thời điểm."},
    {"name": "Queen of Wands",    "viet": "Nữ Hoàng Gậy",       "img": "Queen-of-Wands-Tarot.jpg",  "mean": "Tự tin, quyến rũ, lãnh đạo bằng cảm hứng. Năng lượng tích cực lan tỏa."},
    {"name": "King of Wands",     "viet": "Vua Gậy",            "img": "King-of-Wands-Tarot.jpg",   "mean": "Tầm nhìn, lãnh đạo mạnh mẽ, quyết đoán. Hãy làm chủ vận mệnh của mình."},
    
    # ─── MINOR ARCANA – CUPS (Chén / Nước) ─────────────────────────────────
    {"name": "Ace of Cups",       "viet": "Át Chén",            "img": "Cups01.jpg",     "mean": "Tình yêu mới, cảm xúc trào dâng, khởi đầu của một mối quan hệ đẹp."},
    {"name": "Two of Cups",       "viet": "Hai Chén",           "img": "Cups02.jpg",     "mean": "Kết nối, đối tác, tình cảm hòa hợp. Một mối quan hệ ý nghĩa đang nảy sinh."},
    {"name": "Three of Cups",     "viet": "Ba Chén",            "img": "Cups03.jpg",   "mean": "Vui mừng, ăn mừng, tình bạn. Hãy tận hưởng những khoảnh khắc bên người thân!"},
    {"name": "Four of Cups",      "viet": "Bốn Chén",           "img": "Cups04.jpg",    "mean": "Thiền định, bất mãn, bỏ lỡ cơ hội. Hãy nhìn lại và trân trọng những gì đang có."},
    {"name": "Five of Cups",      "viet": "Năm Chén",           "img": "Cups05.jpg",    "mean": "Mất mát, tiếc nuối, thất vọng. Đừng quên nhìn lại những gì vẫn còn đứng vững."},
    {"name": "Six of Cups",       "viet": "Sáu Chén",           "img": "Cups06.jpg",     "mean": "Hoài niệm, ký ức đẹp, kết nối với quá khứ. Sự ngây thơ và thuần khiết tái hiện."},
    {"name": "Seven of Cups",     "viet": "Bảy Chén",           "img": "Cups07.jpg",   "mean": "Ảo tưởng, lựa chọn quá nhiều, mơ mộng. Hãy tỉnh táo và nhìn rõ thực tế."},
    {"name": "Eight of Cups",     "viet": "Tám Chén",           "img": "Cups08.jpg",   "mean": "Rời bỏ, tìm kiếm điều sâu sắc hơn. Dũng cảm bước đi dù biết sẽ phải bỏ lại."},
    {"name": "Nine of Cups",      "viet": "Chín Chén",          "img": "Cups09.jpg",    "mean": "Mãn nguyện, điều ước thành sự thật, hạnh phúc. Lá bài may mắn nhất bộ!"},
    {"name": "Ten of Cups",       "viet": "Mười Chén",          "img": "Cups10.jpg",     "mean": "Hạnh phúc gia đình, viên mãn tình cảm, bình an. Thiên đường tại nhân gian."},
    {"name": "Page of Cups",      "viet": "Tiểu Thư Chén",      "img": "Cups11.jpg",    "mean": "Nhạy cảm, sáng tạo, tin nhắn tình cảm. Tâm hồn trong sáng và đầy cảm xúc."},
    {"name": "Knight of Cups",    "viet": "Hiệp Sĩ Chén",       "img": "Cups12.jpg",  "mean": "Lãng mạn, theo đuổi lý tưởng, lời mời gọi từ trái tim. Chàng hoàng tử đang đến."},
    {"name": "Queen of Cups",     "viet": "Nữ Hoàng Chén",      "img": "Cups13.jpg",   "mean": "Trực giác mạnh, yêu thương, đồng cảm sâu sắc. Tin vào cảm xúc của mình."},
    {"name": "King of Cups",      "viet": "Vua Chén",           "img": "Cups14.jpg",    "mean": "Cân bằng cảm xúc, khôn ngoan, trưởng thành. Kiểm soát tình cảm mà không dập tắt nó."},
    
    # ─── MINOR ARCANA – SWORDS (Kiếm / Gió) ─────────────────────────────────
    {"name": "Ace of Swords",     "viet": "Át Kiếm",            "img": "Swords01.jpg",   "mean": "Sự thật, rõ ràng, đột phá. Một ý tưởng sắc bén đang xuyên thủng sự mù mờ."},
    {"name": "Two of Swords",     "viet": "Hai Kiếm",           "img": "Swords02.jpg",   "mean": "Bế tắc, né tránh quyết định, cân bằng mong manh. Hãy tháo bịt mắt và nhìn thẳng."},
    {"name": "Three of Swords",   "viet": "Ba Kiếm",            "img": "Swords03.jpg", "mean": "Đau lòng, phản bội, nỗi đau cảm xúc. Đây là cơn mưa cần thiết để tâm hồn thanh lọc."},
    {"name": "Four of Swords",    "viet": "Bốn Kiếm",           "img": "Swords04.jpg",  "mean": "Nghỉ ngơi, phục hồi, thiền định. Cơ thể và tâm trí cần được nạp năng lượng."},
    {"name": "Five of Swords",    "viet": "Năm Kiếm",           "img": "Swords05.jpg",  "mean": "Xung đột, thất bại đau đớn, chiến thắng rỗng tuếch. Cần gì phải thắng bằng mọi giá?"},
    {"name": "Six of Swords",     "viet": "Sáu Kiếm",           "img": "Swords06.jpg",   "mean": "Dịch chuyển, chuyển đổi, rời xa vùng khó khăn. Đang tiến về phía yên bình hơn."},
    {"name": "Seven of Swords",   "viet": "Bảy Kiếm",           "img": "Swords07.jpg", "mean": "Lừa dối, chiến thuật, né tránh đối đầu. Cẩn thận kẻ chơi trò bịp xung quanh."},
    {"name": "Eight of Swords",   "viet": "Tám Kiếm",           "img": "Swords08.jpg", "mean": "Bị trói buộc, giới hạn tự áp đặt. Thật ra gông xiềng đó chỉ là do bạn nghĩ vậy thôi."},
    {"name": "Nine of Swords",    "viet": "Chín Kiếm",          "img": "Swords09.jpg",  "mean": "Lo âu, ác mộng, tâm trí quá tải. Nỗi sợ thường tệ hơn thực tế — hãy thở đi."},
    {"name": "Ten of Swords",     "viet": "Mười Kiếm",          "img": "Swords10.jpg",   "mean": "Kết thúc đau đớn, chạm đáy, bị phản bội. Nhưng chỉ có thể đi lên từ đây thôi."},
    {"name": "Page of Swords",    "viet": "Tiểu Thư Kiếm",      "img": "Swords11.jpg",  "mean": "Tò mò, cảnh giác, tư duy nhanh. Hãy thu thập thông tin trước khi hành động."},
    {"name": "Knight of Swords",  "viet": "Hiệp Sĩ Kiếm",       "img": "Swords12.jpg","mean": "Xông pha, quyết đoán, đôi khi liều lĩnh. Tốc độ và sắc bén là vũ khí của bạn."},
    {"name": "Queen of Swords",   "viet": "Nữ Hoàng Kiếm",      "img": "Swords13.jpg", "mean": "Thẳng thắn, độc lập, nhìn thấu tim người. Nói thật dù đôi khi đau lòng."},
    {"name": "King of Swords",    "viet": "Vua Kiếm",           "img": "Swords14.jpg",  "mean": "Lý trí, quyền uy, công lý nghiêm minh. Quyết định dựa trên logic, không phải cảm tính."},
    
    # ─── MINOR ARCANA – PENTACLES (Đồng Tiền / Đất) ─────────────────────────
    {"name": "Ace of Pentacles",  "viet": "Át Tiền",            "img": "Ace-of-Pents.jpg","mean": "Cơ hội tài chính mới, tiềm năng vật chất, nền tảng thịnh vượng."},
    {"name": "Two of Pentacles",  "viet": "Hai Tiền",           "img": "Two-of-Pents.jpg","mean": "Cân bằng, linh hoạt, quản lý nhiều việc cùng lúc. Đừng để quả bóng nào rơi."},
    {"name": "Three of Pentacles","viet": "Ba Tiền",            "img": "Three-of-Pents.jpg","mean": "Hợp tác, kỹ năng được công nhận, làm việc nhóm hiệu quả."},
    {"name": "Four of Pentacles", "viet": "Bốn Tiền",           "img": "Four-of-Pents.jpg","mean": "Kiểm soát, tích lũy, đôi khi bủn xỉn. Tiết kiệm là tốt, nhưng đừng ôm khư khư."},
    {"name": "Five of Pentacles", "viet": "Năm Tiền",           "img": "Five-of-Pents.jpg","mean": "Khó khăn tài chính, thiếu thốn, cô đơn. Nhưng sự giúp đỡ gần hơn bạn nghĩ."},
    {"name": "Six of Pentacles",  "viet": "Sáu Tiền",           "img": "Six-of-Pents.jpg","mean": "Cho và nhận, hào phóng, từ thiện. Sự cân bằng trong việc chia sẻ tài nguyên."},
    {"name": "Seven of Pentacles","viet": "Bảy Tiền",           "img": "Seven-of-Pents.jpg","mean": "Kiên nhẫn chờ đợi thu hoạch, đầu tư dài hạn. Đã gieo thì phải đợi gặt."},
    {"name": "Eight of Pentacles","viet": "Tám Tiền",           "img": "Eight-of-Pents.jpg","mean": "Chuyên cần, học hỏi, rèn giũa kỹ năng. Hãy làm chủ nghề của mình từng ngày."},
    {"name": "Nine of Pentacles", "viet": "Chín Tiền",          "img": "Nine-of-Pents.jpg","mean": "Độc lập, thịnh vượng, tự làm chủ. Công sức đã cho ra trái ngọt xứng đáng."},
    {"name": "Ten of Pentacles",  "viet": "Mười Tiền",          "img": "Ten-of-Pents.jpg","mean": "Di sản, an toàn gia đình, thịnh vượng bền vững. Nền tảng vững chắc cho thế hệ sau."},
    {"name": "Page of Pentacles", "viet": "Tiểu Thư Tiền",      "img": "Page-of-Pents.jpg","mean": "Tham vọng, học hỏi thực tế, cơ hội mới đang nảy mầm. Hãy đặt mục tiêu cụ thể."},
    {"name": "Knight of Pentacles","viet": "Hiệp Sĩ Tiền",      "img": "Knight-of-Pents.jpg","mean": "Chăm chỉ, đáng tin cậy, tiến đều và chắc chắn. Chậm mà chắc, không bỏ cuộc."},
    {"name": "Queen of Pentacles","viet": "Nữ Hoàng Tiền",      "img": "Queen-of-Pents.jpg","mean": "Thực tế, nuôi dưỡng, quản lý tài chính giỏi. Biết cân bằng giữa công việc và gia đình."},
    {"name": "King of Pentacles", "viet": "Vua Tiền",           "img": "King-of-Pents.jpg","mean": "Thành công vật chất, ổn định, lãnh đạo kinh doanh. Thành quả sau bao năm xây dựng."},
]

# Tương thích ngược với TAROT_CARDS cũ (dùng cho /tarot ngày xưa nếu có code nào tham chiếu)
TAROT_CARDS = {c["name"]: {"mean": c["mean"]} for c in TAROT_CARDS_78}

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
TAROT_FOLDER = os.path.join(BASE_DIR, "tarot", "")
TAROT_TABLE_IMG = os.path.join(BASE_DIR, "assets", "table_tarot.jpg")

BAUCUA_FACES = {'bầu': '🥒 Bầu', 'cua': '🦀 Cua', 'tôm': '🦐 Tôm', 'cá': '🐟 Cá', 'gà': '🐓 Gà', 'nai': '🦌 Nai'}

BAUCUA_ICONS = {
    'bầu': 'bau.png',
    'cua': 'crab.png',
    'tôm': 'shrimp.png',
    'cá': 'fish.png',
    'gà': 'chicken.png',
    'nai': 'deer.png'
}

ALTP_PRIZES = {
    1: 100, 2: 200, 3: 300, 4: 500, 5: 1000,
    6: 2000, 7: 3000, 8: 5000, 9: 10000, 10: 20000,
    11: 30000, 12: 40000, 13: 60000, 14: 85000, 15: 100000
}

DEFAULT_BUSINESS_CONFIG = {
    "1": {
        "id_nganh": "th", "ten_nganh": "Cửa hàng Tạp hóa 🏪",
        "quy_mo": {
            "1": {"ten": "Tạp hóa Nhỏ", "von": 2000, "lai": 1000, "thoi_gian": 18000},    
            "2": {"ten": "Tạp hóa Vừa", "von": 3000, "lai": 1500, "thoi_gian": 18000},   
            "3": {"ten": "Tạp hóa Lớn", "von": 4500, "lai": 2300, "thoi_gian": 18000},   
            "4": {"ten": "Siêu thị", "von": 10000, "lai": 5000, "thoi_gian": 18000}       
        }
    }}

xidach_games = {} 
pending_tarot_sessions = {}  # {user_name: {"step": "waiting_question"|"waiting_numbers", "question": "..."}} 

# ==============================================================================
# 🗄️ HÀM XỬ LÝ DỮ LIỆU & TIỀN TỆ
# ==============================================================================

# ==============================================================================
# 🗄️ HÀM XỬ LÝ DỮ LIỆU BẰNG SIÊU TỐC BẰNG SQLITE
# ==============================================================================
import sqlite3
import threading # Thêm thư viện Lock

# ==============================================================================
# 🗄️ DATABASE LAYER — Thread-local connections + write-only lock
#
# WAL mode cho phép N reader song song với 1 writer.
# threading.Lock() cũ chặn tất cả → WAL vô dụng.
# Fix: mỗi thread có connection riêng → SELECT không cần lock,
#      chỉ dùng _write_lock cho INSERT/UPDATE/DELETE.
# ==============================================================================
DB_PATH = "ten_bot_data.db"
_thread_local = threading.local()   # Mỗi thread giữ connection riêng
_write_lock   = threading.Lock()    # Chỉ lock khi ghi — không lock khi đọc

def _init_db():
    """Tạo bảng và bật WAL. Chỉ gọi 1 lần lúc startup."""
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")   # An toàn với WAL, nhanh hơn FULL
    conn.execute("PRAGMA cache_size=-16000")    # 16 MB page cache
    conn.execute("PRAGMA temp_store=MEMORY")
    conn.execute("CREATE TABLE IF NOT EXISTS json_store (filename TEXT PRIMARY KEY, data TEXT)")
    conn.commit()
    conn.close()

_init_db()

def _get_conn() -> sqlite3.Connection:
    """
    Trả về connection SQLite của thread đang gọi.
    Tự tạo mới nếu thread chưa có — thread-local nên không cần lock.
    """
    if not hasattr(_thread_local, "conn"):
        conn = sqlite3.connect(DB_PATH, check_same_thread=True)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA cache_size=-16000")
        conn.execute("PRAGMA temp_store=MEMORY")
        _thread_local.conn = conn
    return _thread_local.conn

def migrate_json_to_db():
    files_to_migrate = [DATA_FILE, TAROT_FILE, COIN_FILE, LOAN_FILE, CREDIT_FILE, JOBS_FILE, STREAKS_FILE, ALTP_FILE, BUSINESS_FILE, ASSETS_FILE, P2P_FILE, GOLD_FILE, ALTP_WINNERS_FILE, PROFILE_FILE, AVATAR_FILE, INVENTORY_FILE, MARKET_FILE, "daily_business_stats.json", "wallet_data.json", "personal_data.json"]
    migrated_count = 0
    with _write_lock:
        conn = _get_conn()
        for f in files_to_migrate:
            if os.path.exists(f):
                try:
                    with open(f, "r", encoding="utf-8") as file:
                        content = file.read()
                    conn.execute("INSERT OR REPLACE INTO json_store (filename, data) VALUES (?, ?)", (f, content))
                    os.rename(f, f + ".bak")
                    migrated_count += 1
                except Exception as e:
                    print(f"⚠️ Lỗi chuyển đổi {f}: {e}")
        if migrated_count > 0:
            conn.commit()
            print(f"✅ ĐẠI PHẪU THÀNH CÔNG: Đã hút {migrated_count} file JSON chuyển sang DB!")

migrate_json_to_db()

def migrate_bb_to_th():
    """
    Migration 1 lần: Đổi key 'bb' → 'th' trong inventory_data và market_data
    đang lưu trong DB (SQLite). Tự bỏ qua nếu đã migrate rồi.
    Dùng SQLite trực tiếp vì load_json_data chưa được định nghĩa tại thời điểm này.
    """
    conn = _get_conn()

    def _read(filename):
        row = conn.execute("SELECT data FROM json_store WHERE filename=?", (filename,)).fetchone()
        if row:
            try:
                return json.loads(row[0])
            except Exception:
                return None
        return None

    def _write(filename, data):
        with _write_lock:
            conn.execute(
                "INSERT OR REPLACE INTO json_store (filename, data) VALUES (?, ?)",
                (filename, json.dumps(data, ensure_ascii=False))
            )
            conn.commit()

    # --- 1. INVENTORY: đổi materials["bb"] → materials["th"] cho từng user ---
    raw_inv = _read(INVENTORY_FILE)
    if isinstance(raw_inv, dict):
        inv_changed = False
        for user, inv in raw_inv.items():
            mats = inv.get("materials", {})
            if "bb" in mats:
                mats["th"] = mats.pop("bb")
                inv_changed = True
        if inv_changed:
            _write(INVENTORY_FILE, raw_inv)
            print("✅ [Migration bb→th] Đã đổi key 'bb' → 'th' trong inventory_data!")
        else:
            print("ℹ️  [Migration bb→th] inventory_data: không cần migrate (đã sạch).")
    else:
        print("ℹ️  [Migration bb→th] inventory_data: chưa có dữ liệu trong DB, bỏ qua.")

    # --- 2. MARKET DATA: đổi key "bb" → "th" trong current & previous ---
    raw_market = _read(MARKET_FILE)
    if isinstance(raw_market, dict):
        market_changed = False
        for section in ["current", "previous"]:
            if section in raw_market and "bb" in raw_market[section]:
                raw_market[section]["th"] = raw_market[section].pop("bb")
                market_changed = True
        if market_changed:
            _write(MARKET_FILE, raw_market)
            print("✅ [Migration bb→th] Đã đổi key 'bb' → 'th' trong market_data!")
        else:
            print("ℹ️  [Migration bb→th] market_data: không cần migrate (đã sạch).")
    else:
        print("ℹ️  [Migration bb→th] market_data: chưa có dữ liệu trong DB, bỏ qua.")

migrate_bb_to_th()

def load_bot_config():
    default_config = {"time_notication_morning": "07:00 AM", "time_send_news": ["09:00 AM", "03:00 PM"]}
    config = load_json_data(CONFIG_FILE, default_config)
    needs_update = False
    for key, value in default_config.items():
        if key not in config: config[key] = value; needs_update = True
    if isinstance(config.get("time_send_news"), str):
        config["time_send_news"] = [config["time_send_news"]]; needs_update = True
    if needs_update: save_json_data(CONFIG_FILE, config)
    return config

def load_json_data(filepath, default_data=None):
    """
    Đọc data từ DB. KHÔNG cần lock vì mỗi thread có connection riêng
    và WAL đảm bảo snapshot isolation cho reader.
    """
    if default_data is None: default_data = {}

    if filepath == CONFIG_FILE:
        if os.path.exists(filepath):
            try:
                with open(filepath, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if isinstance(data, type(default_data)): return data
            except Exception as e:
                print(f"⚠️ [load_json] Lỗi đọc file {filepath}: {e}")
        save_json_data(filepath, default_data)
        return default_data

    try:
        row = _get_conn().execute(
            "SELECT data FROM json_store WHERE filename=?", (filepath,)
        ).fetchone()
        if row:
            data = json.loads(row[0])
            if isinstance(data, type(default_data)): return data
    except Exception as e:
        print(f"⚠️ [load_json] Lỗi đọc DB {filepath}: {e}")

    save_json_data(filepath, default_data)
    return default_data

def save_json_data(filepath, data):
    """Ghi data vào DB. Chỉ đoạn execute+commit cần _write_lock."""
    if filepath == CONFIG_FILE:
        try:
            with open(filepath, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=4)
        except Exception as e:
            print(f"⚠️ [save_json] Lỗi ghi file {filepath}: {e}")
        return

    try:
        json_str = json.dumps(data, ensure_ascii=False)
        with _write_lock:
            conn = _get_conn()
            conn.execute(
                "INSERT OR REPLACE INTO json_store (filename, data) VALUES (?, ?)",
                (filepath, json_str)
            )
            conn.commit()
    except Exception as e:
        print(f"❌ Lỗi ghi DB ({filepath}): {e}")

def load_altp_questions():
    if not os.path.exists(ALTP_FILE):
        save_json_data(ALTP_FILE, [])
        return []
    try:
        data = load_json_data(ALTP_FILE, [])
        if not data or not isinstance(data, list): return []
        return data
    except: return []

def get_profile(user_name, profile_data):
    if user_name not in profile_data:
        profile_data[user_name] = {
            "health": 25,
            "max_health": 25,
            "iq": 77.5,
            "management_limit": 5,
            "stress": 0,
            "training": None
        }
    else:
        current_iq = profile_data[user_name].get("iq", 77.5)
        new_limit = 5 + int((current_iq - 77.5) / 5)
        profile_data[user_name]["management_limit"] = new_limit
    return profile_data[user_name]

def format_coin(amount):
    try: val = int(amount)
    except: return "0 xu"
    if val == 0: return "0 xu"
    
    is_neg = val < 0
    val = abs(val)
    
    res = f"{val:,} xu".replace(",", ".")
    return f"-{res}" if is_neg else res

def format_time(seconds):
    hours, remainder = divmod(seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    if hours > 0: return f"{int(hours)}h{int(minutes)}p"
    return f"{int(minutes)}p{int(seconds)}s"

def find_exact_name(name_input, data_dict):
    for key in data_dict.keys():
        if key.lower() == name_input.lower():
            return key
    return name_input

def get_tarot_day():
    now = datetime.datetime.now()
    return f"{now.day}/{now.month}/{now.year}"
    



def add_daily_stat(player, biz_name, emp, rent, salary, gross, net):
    # Dùng RAM cache thay vì load/save DB mỗi lần gọi
    stats = get_daily_stats()
    if player not in stats: stats[player] = {}
    if biz_name not in stats[player]:
        stats[player][biz_name] = {"emp": emp, "rent": 0, "salary": 0, "gross": 0, "net": 0}
    stats[player][biz_name]["emp"] = max(stats[player][biz_name].get("emp", 0), emp)
    stats[player][biz_name]["rent"] += rent
    stats[player][biz_name]["salary"] += salary
    stats[player][biz_name]["gross"] += gross
    stats[player][biz_name]["net"] += net
    mark_daily_stats_dirty()  # Flush async, không ghi DB ngay

# ==============================================================================
# 🎮 LOGIC API VÀNG (GIAVANG.ORG)
# ==============================================================================
cached_gold = None
last_fetch_gold = 0

def get_gold_prices():
    global cached_gold, last_fetch_gold
    if time.time() - last_fetch_gold < 300 and cached_gold:
        return cached_gold
    try:
        headers = {"User-Agent": "Mozilla/5.0"}
        r = requests.get("https://giavang.org/", headers=headers, timeout=10)
        soup = BeautifulSoup(r.text, 'html.parser')
        
        time_elem = soup.find('h1', class_='box-headline')
        time_str = time_elem.find('small').text.strip() if time_elem and time_elem.find('small') else "Vừa xong"
        
        mieng_mua = 0; mieng_ban = 0; nhan_mua = 0; nhan_ban = 0

        vm_tag = soup.find(lambda tag: tag.name == "a" and "Giá vàng Miếng SJC" in tag.text)
        if vm_tag:
            vm_row = vm_tag.find_parent('h2').find_next_sibling('div', class_='row')
            prices = vm_row.find_all('span', class_='gold-price')
            p1 = int(prices[0].text.split()[0].replace('.', '')) // GOLD_RATE_DIVISOR
            p2 = int(prices[1].text.split()[0].replace('.', '')) // GOLD_RATE_DIVISOR
            mieng_mua = min(p1, p2)
            mieng_ban = max(p1, p2)

        vn_tag = soup.find(lambda tag: tag.name == "a" and "Giá vàng Nhẫn SJC" in tag.text)
        if vn_tag:
            vn_row = vn_tag.find_parent('h2').find_next_sibling('div', class_='row')
            prices = vn_row.find_all('span', class_='gold-price')
            p1 = int(prices[0].text.split()[0].replace('.', '')) // GOLD_RATE_DIVISOR
            p2 = int(prices[1].text.split()[0].replace('.', '')) // GOLD_RATE_DIVISOR
            nhan_mua = min(p1, p2)
            nhan_ban = max(p1, p2)

        cached_gold = {
            "time": time_str,
            "mieng_mua": mieng_mua, "mieng_ban": mieng_ban,
            "nhan_mua": nhan_mua, "nhan_ban": nhan_ban
        }
        last_fetch_gold = time.time()
        return cached_gold
    except Exception as e:
        return cached_gold

# ==============================================================================
# HÀM LẤY TIN TỨC VÀ LỜI CHÀO
# ==============================================================================

def get_loi_chao_buoi_sang():
    now = datetime.datetime.now()
    solar = Solar(now.year, now.month, now.day)
    lunar = Converter.Solar2Lunar(solar)
    colors = ["Đỏ", "Cam", "Vàng", "Xanh lá cây", "Xanh dương", "Tím", "Hồng", "Trắng", "Đen"]
    msg = (f"🌅 Chào buổi sáng cả nhà!\n"
           f"📅 Dương lịch: {now.day}/{now.month}/{now.year}\n"
           f"🌕 Âm lịch: {lunar.day}/{lunar.month}/{lunar.year}\n"
           f"🎨 Màu nhân phẩm hôm nay: {random.choice(colors)}\n\n"
           f"🔮 Vũ trụ đang gửi tín hiệu! Gõ '/tarot' để bốc 1 lá bài nha.")
    return msg

def fetch_vnexpress_top_story():
    try:
        url = "https://vnexpress.net/"
        headers = {"User-Agent": "Mozilla/5.0"}
        r = requests.get(url, headers=headers, timeout=10)
        soup = BeautifulSoup(r.text, 'html.parser')
        top_article = soup.find('article', class_='item-news full-thumb article-topstory') or soup.find('article', class_='item-news')
        if top_article:
            title_tag = top_article.find('h3', class_='title-news') or top_article.find('h1', class_='title-news') 
            a_tag = title_tag.find('a')
            title, link = a_tag.text.strip(), a_tag['href']
            desc_tag = top_article.find('p', class_='description')
            desc = desc_tag.text.strip() if desc_tag else "Click vào link để xem chi tiết."
            return f"📰 ĐIỂM TIN NÓNG VNEXPRESS 📰\n\n📌 {title}\n📝 {desc}\n👉 Đọc ngay: {link}"
        return None
    except: return None

# ==============================================================================
# 🎮 LUỒNG LẮNG NGHE ADMIN TỪ CMD
# ==============================================================================

def admin_console_thread():
    while True:
        try:
            cmd = input().strip()
            if cmd.startswith("/"):
                admin_cmd_queue.put(cmd)
        except EOFError:
            time.sleep(1) # Tránh lặp vô hạn gây lỗi nếu chạy nền
        except Exception:
            time.sleep(1)
# ==============================================================================
# 🎮 LOGIC GAME BÀI, BẦU CUA & SỰ KIỆN PHẠT NGHIỆP QUẬT
# ==============================================================================

def check_and_apply_penalty(user_name, game_name, bet_amt, coin_data, player_streaks):
    if user_name not in player_streaks: player_streaks[user_name] = {"game": game_name, "count": 1}
    else:
        if player_streaks[user_name]["game"] == game_name: player_streaks[user_name]["count"] += 1
        else: player_streaks[user_name] = {"game": game_name, "count": 1}

    save_json_data(STREAKS_FILE, player_streaks) 
    count = player_streaks[user_name]["count"]

    if count > 5: 
        if random.randint(1, 100) <= 30: 
            player_streaks[user_name]["count"] = 0 
            save_json_data(STREAKS_FILE, player_streaks) 
            
            event_type = random.randint(1, 4)
            if event_type == 1:
                coin_data[user_name] = coin_data.get(user_name, 0) - 150
                save_json_data(COIN_FILE, coin_data)
                return f"🚑 OÉT OÉT! {user_name} cày {game_name} liên tục {count} ván nên ngất xỉu do quá sức!\nTiền cược được hoàn trả, nhưng phải đi cấp cứu tốn 150 xu!"
            elif event_type == 2:
                coin_data[user_name] = coin_data.get(user_name, 0) - (bet_amt + 200)
                save_json_data(COIN_FILE, coin_data)
                return f"🚓 CHÍU CHÍU! Công an ập vào sòng! {user_name} bị tóm cổ!\nBị tịch thu tiền cược ván này ({bet_amt}) và nộp phạt thêm 200 xu!"
            elif event_type == 3:
                coin_data[user_name] = coin_data.get(user_name, 0) - 150
                save_json_data(COIN_FILE, coin_data)
                return f"🤕 ỐI DỒI ÔI! {user_name} cày nhiều quá hoa mắt ngã cầu thang, rơi mất 150 xu!\n(Tiền cược ván này được hoàn trả)."
            elif event_type == 4:
                coin_data[user_name] = coin_data.get(user_name, 0) - 50
                save_json_data(COIN_FILE, coin_data)
                return f"🤡 LÚ NỮA ĐI! {user_name} chơi mờ cả mắt, lỡ tay bấm nhầm bị giang hồ lừa mất 50 xu!\n(Ván này bị hủy)."
    return None

def create_deck():
    suits = ['♠', '♣', '♦', '♥']
    ranks = ['2', '3', '4', '5', '6', '7', '8', '9', '10', 'J', 'Q', 'K', 'A']
    return [r + s for s in suits for r in ranks]

def get_card_value(card):
    rank = card[:-1]
    if rank in ['J', 'Q', 'K']: return 10
    if rank == 'A': return 11
    return int(rank)

def calculate_score(hand):
    score, aces = 0, 0
    for card in hand:
        rank = card[:-1]
        if rank == 'A': aces += 1; score += 11
        elif rank in ['J', 'Q', 'K']: score += 10
        else: score += int(rank)
    while score > 21 and aces > 0:
        score -= 10; aces -= 1
    return score

def check_special_hand(hand):
    if len(hand) == 2:
        r1, r2 = hand[0][:-1], hand[1][:-1]
        if r1 == 'A' and r2 == 'A': return "Xì Bàng"
        if (r1 == 'A' and get_card_value(hand[1]) == 10) or (r2 == 'A' and get_card_value(hand[0]) == 10): return "Xì Dách"
    return "Thường"

def calculate_baicao_score(hand):
    ranks = [card[:-1] for card in hand]
    if all(r in ['J', 'Q', 'K'] for r in ranks): return 99 
    score = 0
    for r in ranks:
        if r == 'A': score += 1
        elif r in ['J', 'Q', 'K']: score += 10
        else: score += int(r)
    return score % 10

def format_baicao_score(score):
    return "3 TÂY (Ba Tiên)" if score == 99 else f"{score} điểm"

# ==============================================================================
# 🛠️ BỘ XỬ LÝ LỆNH TRUNG TÂM
# ==============================================================================

def xu_ly_lenh(user_name, message_text, mentioned_names, user_msg_counts, tarot_data, coin_data, loan_data, credit_data, pending_loans, jobs_data, player_streaks, altp_games, business_config, assets_data, p2p_data, pending_p2p, xidach_games, gold_data, altp_winners_data, profile_data, user_avatars, caro_games, pending_caro, base64_img=None):
    msg = message_text.strip().lower()
    cmd_parts = msg.split()
    cmd = cmd_parts[0] if len(cmd_parts) > 0 else ""
    
    if msg == "/api":
        keys_data = load_json_data(API_KEYS_FILE, {"keys": []})
        api_keys = keys_data.get("keys", [])
        if not api_keys: return "❌ Chưa có API Key nào trong kho!"
        
        now = time.time()
        res = "🎛️ BẢNG ĐIỀU KHIỂN NĂNG LƯỢNG AI 🎛️\n"
        
        for i, key in enumerate(api_keys):
            # Lọc lại danh sách req trong 60s qua
            if key in api_usage_tracker:
                api_usage_tracker[key] = [t for t in api_usage_tracker[key] if now - t < 60]
                used = len(api_usage_tracker[key])
            else:
                used = 0
                
    # ===========================================================================
    # 🔮 TAROT SESSION INTERCEPTOR – Bắt tin nhắn trong luồng bói bài
    # ===========================================================================
    if not msg.startswith(PREFIX) and user_name in pending_tarot_sessions:
        session = pending_tarot_sessions[user_name]
        step = session.get("step")

        # BƯỚC 2: Người dùng vừa gửi câu hỏi
        if step == "waiting_question":
            if not message_text.strip():
                return "🔮 Ê, câu hỏi đâu? Gõ điều bạn đang băn khoăn vào đây nào!"
            session["question"] = message_text.strip()
            session["step"] = "waiting_numbers"
            return [
                f"✨ Tẻn đã nhận được câu hỏi của {user_name}!\n🃏 Tẻn đang xào bài và tập trung suy nghĩ về câu hỏi của bạn để truyền năng lượng ý niệm...",
                "🎴 Bây giờ hãy chọn 3 con số từ 1 đến 78, cách nhau bằng dấu cách.\n📌 Ví dụ: 10 35 62\n(Hãy tin vào trực giác của bạn, đừng suy nghĩ quá nhiều!)"
            ]

        # BƯỚC 3: Người dùng vừa gửi 3 số
        if step == "waiting_numbers":
            parts = message_text.strip().split()
            nums = []
            for p in parts:
                try:
                    n = int(p)
                    if 1 <= n <= 78:
                        nums.append(n)
                except:
                    pass
            if len(nums) < 3:
                return "⚠️ Tẻn cần đúng 3 con số hợp lệ từ 1–78 nha! Thử lại đi ví dụ: 10 35 62"

            nums = nums[:3]
            question = session.get("question", "")
            del pending_tarot_sessions[user_name]  # Xoá session, kết thúc luồng

            # 🧠 BÍ THUẬT XÀO BÀI THẬT SỰ (SHUFFLE)
            deck = TAROT_CARDS_78.copy() # Lấy nguyên 1 bộ bài mới tinh
            random.shuffle(deck)         # Trộn lên tung tóe ngẫu nhiên 100%

            # Lấy 3 lá bài theo số chọn (index = số - 1) trên bộ bài ĐÃ XÀO
            pos_labels = ["🌑 Quá Khứ", "🌕 Hiện Tại", "🌟 Tương Lai"]
            selected_cards = []
            for i, n in enumerate(nums):
                card = deck[n - 1] # 👈 Bốc từ bộ deck đã trộn, chứ ko bốc từ cục tĩnh nữa
                selected_cards.append({**card, "pos": pos_labels[i], "num": n})

            # Build danh sách tin nhắn gửi đi (list hỗn hợp text + ảnh)
            messages_to_send = []
            messages_to_send.append(
                f"🔮 Vũ trụ đã lên tiếng! {user_name} bốc được 3 lá sau:\n"
                + "\n".join([f"{c['pos']} → #{c['num']} {c['name']} ({c['viet']})" for c in selected_cards])
            )

            # Gửi từng lá kèm ảnh + ý nghĩa
            for c in selected_cards:
                img_path = TAROT_FOLDER + c["img"]
                caption = f"{c['pos']}\n🃏 {c['name']} – {c['viet']}\n📜 {c['mean']}"
                messages_to_send.append({"type": "image", "path": img_path, "caption": caption})

            return messages_to_send

    # ===========================================================================
    # 🎬 TẢI VIDEO ĐA NỀN TẢNG (X, Facebook, YouTube, Instagram...)
    # ===========================================================================
    if cmd in ["/video", "/v"]:
        parts = message_text.split(maxsplit=1)
        if len(parts) < 2:
            return "❌ Cú pháp: /video [link_video]\n📌 Hỗ trợ: Youtube, Facebook, X (Twitter), Instagram, TikTok..."

        target_url = parts[1].strip().strip("<>").strip()
        if not (target_url.startswith("http://") or target_url.startswith("https://")):
            return "Liên kết không được hỗ trợ"

        video_file = download_video_web(target_url, BASE_DIR)
        if not video_file or not os.path.exists(video_file):
            return "Liên kết không được hỗ trợ"

        return {"type": "video", "path": video_file, "caption": f"🎬 Video từ: {target_url}"}

    if msg in ["/menu", "/help"]:
        return """--- 🎰 HỆ SINH THÁI TẺN ---
👉 /profile hoặc /p : Xem hồ sơ cá nhân
👉 /khoinghiep hoặc /kn : Mở cửa hàng
👉 /kn : Xem danh mục ngành kinh doanh
👉 /taisan : Xem tài sản đang có
👉 /giaithe [ID] : Giải thể Cửa hàng/Công ty (-50% vốn)
👉 /up [ID] : Nâng cấp Cửa hàng/Công ty
👉 /tien hoặc /coin hoặc /xu : Xem ví
👉 /vibot : Xem ví xu của Tẻn
👉 /chuyenxu @Tên Số_xu : Tặng tiền
👉 /vay / /tra : Vay tiền hệ thống
👉 /chovay @Tên [xu] [%_lãi] [giờ]
👉 /nhanvay @Tên : Nhận nợ P2P
👉 /tratien @Tên [xu] : Trả nợ P2P
👉 /sietno @Tên : Siết nợ P2P khi tới hạn

--- 📸 CÁ NHÂN & THÔNG TIN ---
👉 /album : Xem album ảnh
👉 /vitri @Tên : Lấy Google Maps
👉 /stk @Tên : Lấy STK ngân hàng

--- 💰 THỊ TRƯỜNG VÀNG SJC ---
👉 /giavang hoặc /gv : Xem giá vàng
👉 /muavang hoặc /mv : Mua vàng
👉 /mvm [SL] | /mvn [SL] : Mua V.Miếng/V.Nhẫn
👉 /banvang hoặc /bv : Bán vàng
👉 /bvm [SL] | /bvn [SL] : Bán V.Miếng/V.Nhẫn
👉 /chuyenvang @Tên [SL] [nhan/mieng]

--- 🎮 GAME ---
👉 /slot : Máy đánh bạc nổ hũ (500 xu)
👉 /altp : Ai Là Triệu Phú (Vé: 50 xu)
👉 /chanle / /xidach / /baicao / /baucua / /caro

🌾 /lamruong | 🐟 /danhca | 🏍️ /xeom | 🗑️ /vechai
--- 🔮 TÍNH NĂNG KHÁC ---
👉 /video [link] : Tải video (X, Facebook, Youtube, Insta...)
👉 /tarot : Bốc bài Tarot (50 xu/lần)
👉 /pick [A] [B] : Chọn ngẫu nhiên
👉 /roll : Đổ xúc xắc
👉 /top : Bảng xếp hạng chat"""

    if cmd in ["/album", "/vitri", "/stk"]:
        personal_data = load_json_data("personal_data.json", {})
        if cmd == "/album":
            return "📸 Mời các bạn xem album ảnh tại đây:\n👉 https://photos.app.goo.gl/s2V6CCbiFy68QRqG7"
        if cmd == "/vitri":
            if not mentioned_names: return "❌ Bạn phải tag tên người muốn xem vị trí! VD: /vitri @Tên"
            target = mentioned_names[0]
            target_exact = find_exact_name(target, personal_data)
            if target_exact in personal_data and "vitri" in personal_data[target_exact]:
                return f"📍 Vị trí nhà của {target_exact}:\n👉 {personal_data[target_exact]['vitri']}"
            return f"❌ Tẻn chưa có thông tin vị trí của {target}!"
        if cmd == "/stk":
            if not mentioned_names: return "❌ Bạn phải tag tên người muốn xem STK! VD: /stk @Tên"
            target = mentioned_names[0]
            target_exact = find_exact_name(target, personal_data)
            if target_exact in personal_data and "stk" in personal_data[target_exact]:
                return f"💳 Thông tin thanh toán của {target_exact}:\n👉 {personal_data[target_exact]['stk']}"
            return f"❌ Tẻn chưa có thông tin STK của {target}!"

    if cmd in ["/p", "/profile"]:
        pf = get_profile(user_name, profile_data)
        save_json_data(PROFILE_FILE, profile_data)
        
        inventory_data = get_inventory_data()
        user_inv = inventory_data.get(user_name, {"current_bg": "background-df"})
        bg_id = user_inv.get("current_bg", "background-df")
        
        used_management = 0.0
        if user_name in assets_data and assets_data[user_name].get("businesses"):
            for b in assets_data[user_name]["businesses"]:
                qm_id = int(b.get("id_quy_mo", 1))
                if b.get("id_nganh") == "xd":
                    used_management += 2 if qm_id <= 2 else 3
                else:
                    used_management += 1 if qm_id <= 2 else 2

                used_management += b.get("employees", 0) * 0.5
        balance = coin_data.get(user_name, 0)
        user_assets = assets_data.get(user_name, {"businesses": []})
        u_gold = gold_data.get(user_name, {"nhan": 0, "mieng": 0})
        total_value = balance
        gp = get_gold_prices()
        if u_gold.get("nhan", 0) > 0 and gp: total_value += u_gold["nhan"] * gp.get("nhan_mua", 0)
        if u_gold.get("mieng", 0) > 0 and gp: total_value += u_gold["mieng"] * gp.get("mieng_mua", 0)
        if user_assets.get("businesses", []):
            for b in user_assets["businesses"]: total_value += b["von"]

        avatar_url = user_avatars.get(user_name, "")
        img_path = tao_anh_profile(user_name, pf, used_management, balance, total_value, avatar_url, bg_id)
        caption = "👉 Các lệnh rèn luyện:\n🏃 /chaybo | 🏋️ /tapgym | 🔋 /uongnuoc | ♨️ /tamsuoi\n📚 /docsach | 📝 /lambaitest | 🎓 /hocnangcao | 🏫 /hocdaihan"
        
        return {"type": "image", "path": img_path, "caption": caption}

    # --- 💰 THỊ TRƯỜNG VÀNG SJC ---
    if cmd in ["/giavang", "/gv"]:
        gp = get_gold_prices()
        if not gp: return "❌ Tẻn không kết nối được với tiệm vàng, thử lại sau nhé!"
        res = f"🌟 BẢNG GIÁ VÀNG SJC (Nguồn: Giavang.org) 🌟\n{gp['time']}\n\n"
        res += f"🥇 Vàng Miếng SJC:\n- Mua vào (Bạn bán): {gp['mieng_mua']:,} xu/lượng\n- Bán ra (Bạn mua): {gp['mieng_ban']:,} xu/lượng\n\n"
        res += f"💍 Vàng Nhẫn SJC:\n- Mua vào (Bạn bán): {gp['nhan_mua']:,} xu/lượng\n- Bán ra (Bạn mua): {gp['nhan_ban']:,} xu/lượng\n"
        res += "\n👉 Dùng /muavang hoặc /banvang để lướt sóng nhé!"
        return res

    if cmd in ["/muavang", "/mv"]:
        gp = get_gold_prices()
        if not gp: return "❌ Hệ thống tiệm vàng đang bảo trì!"
        res = f"🏦 TIỆM VÀNG TẺN 🏦\nGiá bán ra hiện tại:\n🥇 Vàng Miếng SJC: {gp['mieng_ban']:,} xu/lượng\n💍 Vàng Nhẫn SJC: {gp['nhan_ban']:,} xu/lượng\n\n"
        res += "👉 Để mua, gõ lệnh:\n/mvm [số lượng] (Mua Vàng Miếng)\n/mvn [số lượng] (Mua Vàng Nhẫn)"
        return res

    if cmd in ["/mvm", "/mvn"]:
        gp = get_gold_prices()
        if not gp: return "❌ Hệ thống tiệm vàng đang bảo trì!"
        
        if user_name not in gold_data: gold_data[user_name] = {"nhan": 0, "mieng": 0, "last_trade": 0}
        last_trade = gold_data[user_name].get("last_trade", 0)
        
        if time.time() - last_trade < 600:
            rem = int(600 - (time.time() - last_trade))
            return f"⏳ CẢNH BÁO SPAM GIAO DỊCH: Bạn vừa mua/bán vàng gần đây! Ủy ban chứng khoán Tẻn yêu cầu chờ {format_time(rem)} nữa mới được thao tác tiếp."
            
        gold_type = "mieng" if cmd == "/mvm" else "nhan"
        type_str = "Vàng Miếng" if gold_type == "mieng" else "Vàng Nhẫn"
        
        try: amount = int(cmd_parts[1])
        except: return f"❌ Cú pháp: {cmd} [số lượng]"
            
        if amount <= 0: return "❌ Số lượng mua phải lớn hơn 0!"
        
        price_per_item = gp["mieng_ban"] if gold_type == "mieng" else gp["nhan_ban"]
        total_cost = price_per_item * amount
        balance = coin_data.get(user_name, 0)
        
        if balance < total_cost:
            return f"❌ Nghèo! {user_name} cần {format_coin(total_cost)} để mua {amount} lượng {type_str}, nhưng ví chỉ có {format_coin(balance)}."
            
        coin_data[user_name] -= total_cost
        save_json_data(COIN_FILE, coin_data)
        
        gold_data[user_name][gold_type] = gold_data[user_name].get(gold_type, 0) + amount
        gold_data[user_name]["last_trade"] = time.time()
        save_json_data(GOLD_FILE, gold_data)
        
        return f"✅ GIAO DỊCH THÀNH CÔNG!\n{user_name} đã MUA {amount} lượng {type_str} với giá {format_coin(total_cost)}.\n💰 Ví còn: {format_coin(coin_data[user_name])}."

    if cmd in ["/banvang", "/bv"]:
        gp = get_gold_prices()
        if not gp: return "❌ Hệ thống tiệm vàng đang bảo trì!"
        res = f"🏦 TIỆM VÀNG TẺN 🏦\nGiá thu mua hiện tại:\n🥇 Vàng Miếng SJC: {gp['mieng_mua']:,} xu/lượng\n💍 Vàng Nhẫn SJC: {gp['nhan_mua']:,} xu/lượng\n\n"
        res += "👉 Để bán, gõ lệnh:\n/bvm [số lượng] (Bán Vàng Miếng)\n/bvn [số lượng] (Bán Vàng Nhẫn)"
        return res

    if cmd in ["/bvm", "/bvn"]:
        gp = get_gold_prices()
        if not gp: return "❌ Hệ thống tiệm vàng đang bảo trì!"
        
        if user_name not in gold_data: gold_data[user_name] = {"nhan": 0, "mieng": 0, "last_trade": 0}
        last_trade = gold_data[user_name].get("last_trade", 0)
        
        if time.time() - last_trade < 600:
            rem = int(600 - (time.time() - last_trade))
            return f"⏳ CẢNH BÁO SPAM GIAO DỊCH: Chờ {format_time(rem)} nữa mới được bán lướt sóng nhé."
            
        gold_type = "mieng" if cmd == "/bvm" else "nhan"
        type_str = "Vàng Miếng" if gold_type == "mieng" else "Vàng Nhẫn"
        
        try: amount = int(cmd_parts[1])
        except: return f"❌ Cú pháp: {cmd} [số lượng]"
            
        if amount <= 0: return "❌ Số lượng bán phải lớn hơn 0!"
        if gold_data[user_name].get(gold_type, 0) < amount:
            return f"❌ Chém gió à! {user_name} không có đủ {amount} lượng {type_str} để bán!"
            
        price_per_item = gp["mieng_mua"] if gold_type == "mieng" else gp["nhan_mua"]
        total_earn = price_per_item * amount
        
        gold_data[user_name][gold_type] -= amount
        gold_data[user_name]["last_trade"] = time.time()
        save_json_data(GOLD_FILE, gold_data)
        
        coin_data[user_name] = coin_data.get(user_name, 0) + total_earn
        save_json_data(COIN_FILE, coin_data)
        
        return f"✅ GIAO DỊCH THÀNH CÔNG!\n{user_name} đã BÁN {amount} lượng {type_str} thu về {format_coin(total_earn)}.\n💰 Ví hiện tại: {format_coin(coin_data[user_name])}."

    if cmd in ["/chuyenvang", "/cv"]:
        if len(cmd_parts) < 3: return "❌ Cú pháp: /chuyenvang @Tên [số lượng] [nhan/mieng]"
        try:
            if mentioned_names: target_name = mentioned_names[0]
            else: target_name = " ".join(cmd_parts[1:-1]).replace("@", "").strip() 
            
            target_name = find_exact_name(target_name, coin_data) 

            last_part = cmd_parts[-1]
            second_last = cmd_parts[-2]
            gold_type = "nhan"
            amount = 1
            
            if last_part.isdigit():
                amount = int(last_part)
                target_name = " ".join(cmd_parts[1:-1]).replace("@", "").strip() if not mentioned_names else target_name
                target_name = find_exact_name(target_name, coin_data)
            else:
                if last_part in ["mieng", "miếng", "m"]: gold_type = "mieng"
                if second_last.isdigit(): 
                    amount = int(second_last)
                    target_name = " ".join(cmd_parts[1:-2]).replace("@", "").strip() if not mentioned_names else target_name
                    target_name = find_exact_name(target_name, coin_data)
                else: return "❌ Không xác định được số lượng vàng."

            if amount <= 0: return "❌ Số lượng vàng phải lớn hơn 0!"
            if target_name.lower() == user_name.lower(): return "❌ Tự chuyển vàng cho bản thân à?"
            
            if user_name not in gold_data or gold_data[user_name].get(gold_type, 0) < amount:
                return f"❌ {user_name} không đủ {amount} lượng vàng {gold_type} để chuyển!"
                
            gold_data[user_name][gold_type] -= amount
            if target_name not in gold_data: gold_data[target_name] = {"nhan": 0, "mieng": 0, "last_trade": 0}
            gold_data[target_name][gold_type] = gold_data[target_name].get(gold_type, 0) + amount
            save_json_data(GOLD_FILE, gold_data)
            
            type_str = "Vàng Nhẫn" if gold_type == "nhan" else "Vàng Miếng"
            return f"🎁 ĐẠI GIA PHÁT LỘC!\n{user_name} đã tặng {amount} lượng {type_str} cho {target_name}!"
        except Exception as e: return f"❌ Lỗi cú pháp. Ví dụ: /cv @Huy 2 mieng"

    if cmd == "/taisan":
        balance = coin_data.get(user_name, 0)
        
        # Lấy dữ liệu Vàng
        u_gold = gold_data.get(user_name, {"nhan": 0, "mieng": 0})
        gp = get_gold_prices()
        if not gp: gp = {"nhan_mua": 0, "nhan_ban": 0, "mieng_mua": 0, "mieng_ban": 0}
            
        # Lấy dữ liệu Cơ sở
        user_assets = assets_data.get(user_name, {"businesses": []})
        businesses = user_assets.get("businesses", [])
        
        # Lấy dữ liệu Kho nguyên liệu
        inventory_data = get_inventory_data()
        user_inv = inventory_data.get(user_name, {})
        
        # Tạo và gửi ảnh
        avatar_url = user_avatars.get(user_name, "")
        img_path = tao_anh_taisan(user_name, balance, u_gold, gp, businesses, user_inv, avatar_url)
        
        caption = "📊 Bảng báo cáo Tài sản & Kinh doanh chi tiết.\n👉 Gõ /kho để xem thêm Đá Ruby và Vật phẩm."
        return {"type": "image", "path": img_path, "caption": caption}

# --- THỊ TRƯỜNG & KHO BÃI ---
    if cmd in ["/giakho", "/gk"]:
        market_data = load_json_data(MARKET_FILE, {})
        cur = market_data.get("current", {"th": 750, "qa": 750, "xd": 750})
        prev = market_data.get("previous", {"th": 750, "qa": 750, "xd": 750})
        
        def get_trend(c, p):
            if c > p: return f"🔺 (+{c-p})"
            elif c < p: return f"🔻 ({c-p})"
            return "➖ (Giữ giá)"
            
        res = "📈 BẢNG GIÁ NGUYÊN VẬT LIỆU (Cập nhật 5h/lần) 📈\n\n"
        res += f"📦 Hàng hóa (Tạp hóa): {cur['th']} xu/sp {get_trend(cur['th'], prev['th'])}\n"
        res += f"🥩 Thực phẩm (Ăn uống): {cur['qa']} xu/sp {get_trend(cur['qa'], prev['qa'])}\n"
        res += f"🧱 Vật liệu (Xây dựng): {cur['xd']} xu/sp {get_trend(cur['xd'], prev['xd'])}\n"
        res += "\n👉 Dùng /nhapkho [th/qa/xd] [số_lượng] để nhập hàng."
        return res

    if cmd in ["/kho", "/k"]:
        inventory_data = get_inventory_data()
        user_inv = inventory_data.get(user_name, {})
        mats = user_inv.get("materials", {"th": 0, "qa": 0, "xd": 0})
        
        res = f"🏭 NHÀ KHO CỦA {user_name.upper()} 🏭\n(Tối đa 100 vật phẩm mỗi loại)\n\n"
        res += f"📦 Hàng hóa (Tạp hóa): {mats.get('th', 0)} / 100\n"
        res += f"🥩 Thực phẩm (Ăn uống): {mats.get('qa', 0)} / 100\n"
        res += f"🧱 Vật liệu (Xây dựng): {mats.get('xd', 0)} / 100\n"
        return res

    if cmd == "/nhapkho":
        parts = message_text.split()
        if len(parts) < 3: return "❌ Cú pháp: /nhapkho [th/qa/xd] [SL] HOẶC /nhapkho nh [ID_Ngân_hàng] [Số_xu]"
        
        nganh = parts[1].lower()
        balance = coin_data.get(user_name, 0)
        
        # --- LUỒNG 1: NHẬP VẬT LIỆU (Tạp hóa, Ăn uống, Xây dựng) ---
        if nganh in ["th", "qa", "xd"]:
            if len(parts) != 3: return f"❌ Cú pháp nhập vật liệu: /nhapkho {nganh} [Số_lượng]"
            try: amount = int(parts[2])
            except: return "❌ Số lượng phải là số nguyên!"
            if amount <= 0: return "❌ Số lượng phải lớn hơn 0."
            
            market_data = load_json_data(MARKET_FILE, {})
            price = market_data.get("current", {}).get(nganh, 750)
            total_cost = price * amount
            
            if balance < total_cost: return f"❌ Thiếu lúa! Cần {format_coin(total_cost)} để mua {amount} {MAT_NAMES[nganh]}, bạn chỉ có {format_coin(balance)}."
            
            inventory_data = get_inventory_data()
            if user_name not in inventory_data: inventory_data[user_name] = {}
            if "materials" not in inventory_data[user_name]: inventory_data[user_name]["materials"] = {"th": 0, "qa": 0, "xd": 0}
            
            current_mat = inventory_data[user_name]["materials"].get(nganh, 0)
            if current_mat + amount > 100: return f"❌ Kho chật! Kho đang có {current_mat}, chỉ có thể nhập thêm tối đa {100 - current_mat} {MAT_NAMES[nganh]} nữa."
            
            coin_data[user_name] -= total_cost
            inventory_data[user_name]["materials"][nganh] = current_mat + amount
            save_json_data(COIN_FILE, coin_data)
            save_inventory_data()
            return f"🚛 NHẬP KHO THÀNH CÔNG!\n{user_name} đã nhập {amount} {MAT_NAMES[nganh]} (Giá: {price}/sp). Tổng thiệt hại: {format_coin(total_cost)}."
            
        # --- LUỒNG 2: NẠP QUỸ NGÂN HÀNG ---
        elif nganh == "nh":
            if len(parts) != 4: return "❌ Cú pháp nạp Quỹ Ngân hàng: /nhapkho nh [ID_Ngân_hàng] [Số_xu]"
            try: 
                biz_id = int(parts[2])
                deposit = int(parts[3])
            except: return "❌ ID và Số xu nạp phải là số nguyên!"
            
            if deposit <= 0: return "❌ Số tiền nạp phải lớn hơn 0!"
            
            user_assets = assets_data.get(user_name, {"businesses": []})
            biz_list = user_assets.get("businesses", [])
            if biz_id < 0 or biz_id >= len(biz_list): return "❌ ID cơ sở không tồn tại."
            
            biz = biz_list[biz_id]
            if biz.get("id_nganh") != "nh": return "❌ Cơ sở này không phải là Ngân hàng!"
            
            if balance < deposit: return f"❌ Không đủ {format_coin(deposit)} trong ví để nạp Quỹ!"
            
            current_reserves = biz.get("bank_reserves", 0)
            max_reserves = biz.get("von", 0)
            if current_reserves + deposit > max_reserves:
                return f"❌ Ngân hàng này chỉ được phép dự trữ tối đa {format_coin(max_reserves)}. Hiện đang có {format_coin(current_reserves)}."
                
            coin_data[user_name] -= deposit
            biz["bank_reserves"] = current_reserves + deposit
            save_json_data(COIN_FILE, coin_data)
            save_json_data(ASSETS_FILE, assets_data)
            return f"💰 NẠP QUỸ THÀNH CÔNG!\nĐã chuyển {format_coin(deposit)} vào Quỹ của '{biz['ten']}'. Số dư Quỹ hiện tại: {format_coin(biz['bank_reserves'])}."
        
        else:
            return "❌ Mã ngành không hợp lệ! Hãy dùng th, qa, xd hoặc nh."

    # --- NHÂN SỰ ---
    if cmd in ["/thuenguoi", "/duoiviec"]:
        parts = message_text.split()
        if len(parts) != 3: return f"❌ Cú pháp: {cmd} [ID_Cơ_sở] [Số_lượng]"
        try: biz_id = int(parts[1]); amount = int(parts[2])
        except: return "❌ ID và Số lượng phải là số nguyên."
        if amount <= 0: return "❌ Số lượng phải lớn hơn 0."
        
        user_assets = assets_data.get(user_name, {"businesses": []})
        biz_list = [b for b in user_assets.get("businesses", []) if b.get("id_nganh") != "nha"]
        if biz_id < 0 or biz_id >= len(biz_list): return "❌ ID cơ sở không tồn tại. Xem /taisan."
        
        biz = biz_list[biz_id]
        qm_id = int(biz.get("id_quy_mo", 1))
        current_emp = biz.get("employees", 0)
        max_emp = MAX_EMP.get(qm_id, 2)
        
        if cmd == "/thuenguoi":
            if current_emp + amount > max_emp: return f"❌ Quy mô hiện tại chỉ chứa tối đa {max_emp} nhân viên (Đang có {current_emp})."
            
            pf = get_profile(user_name, profile_data)
            used_management = 0.0
            for b in biz_list:
                b_qm = int(b.get("id_quy_mo", 1))
                if b.get("id_nganh") == "xd": used_management += 2 if b_qm <= 2 else 3
                else: used_management += 1 if b_qm <= 2 else 2
                used_management += b.get("employees", 0) * 0.5
                
            if used_management + (amount * 0.5) > pf["management_limit"]:
                return f"❌ Vượt giới hạn quản lý! Điểm QL hiện tại là {pf['management_limit']} (Đang dùng {used_management}). Thuê thêm {amount} người cần {amount * 0.5} điểm nữa."
                
            biz["employees"] = current_emp + amount
            save_json_data(ASSETS_FILE, assets_data)
            return f"👷 TUYỂN DỤNG THÀNH CÔNG!\n'{biz['ten']}' vừa nhận thêm {amount} nhân viên. Năng suất sẽ được tăng cường trong chu kỳ tiếp theo!"
            
        elif cmd == "/duoiviec":
            if amount > current_emp: return f"❌ Cơ sở này chỉ đang có {current_emp} nhân viên, không thể đuổi {amount} người!"
            biz["employees"] = current_emp - amount
            save_json_data(ASSETS_FILE, assets_data)
            return f"🥾 ĐUỔI VIỆC THÀNH CÔNG!\nĐã sa thải {amount} nhân viên khỏi '{biz['ten']}'. Chi phí lương sẽ giảm, nhưng lợi nhuận cũng sẽ giảm theo."






    if cmd == "/kho":
        inventory_data = get_inventory_data()
        user_inv = inventory_data.get(user_name, {})
        bgs = user_inv.get("backgrounds", [])
        
        res = f"🎒 KHÔNG GIAN LƯU TRỮ CỦA {user_name} 🎒\n"
        res += f"🖼️ Backgrounds đã có: {len(bgs)}\n"
        if bgs: res += ", ".join(bgs) + "\n"
        else: res += "(Trống)\n"
        res += "\n👉 Gõ /cb [ID] để đổi background hồ sơ. Ví dụ: /cb background-1"
        return res

    if cmd == "/cb":
        if len(cmd_parts) != 2: return "❌ Cú pháp: /cb [ID Background]. Dùng lệnh /kho để xem ID."
        bg_id = cmd_parts[1]
        
        inventory_data = get_inventory_data()
        user_inv = inventory_data.get(user_name, {})
        bgs = user_inv.get("backgrounds", [])
        
        if bg_id != "background-df" and bg_id not in bgs:
            return f"❌ Bạn chưa sở hữu '{bg_id}'. Gõ lệnh /kho để kiểm tra."
            
        user_inv["current_bg"] = bg_id
        save_inventory_data()
        return f"🖼️ ĐỔI NỀN THÀNH CÔNG!\nBạn đã cài đặt '{bg_id}' làm màn nền chính cho Profile của mình. Gõ /p để xem thành quả nhé!"

    if cmd == "/giaithe":
        try: biz_id = int(cmd_parts[1])
        except: return "❌ ID cửa hàng không hợp lệ!"
        
        if user_name not in assets_data or not assets_data[user_name].get("businesses"):
            return "❌ Bạn trắng tay, làm gì có cơ sở kinh doanh nào mà đòi giải thể!"
            
        biz_list = assets_data[user_name]["businesses"]
        if biz_id < 0 or biz_id >= len(biz_list):
            return "❌ ID cửa hàng không tồn tại! Gõ /taisan để xem lại cho chuẩn."
            
        biz = biz_list.pop(biz_id) 
        refund = biz["von"] // 2 
        coin_data[user_name] = coin_data.get(user_name, 0) + refund
        
        save_json_data(COIN_FILE, coin_data)
        save_json_data(ASSETS_FILE, assets_data)
        return f"💥 KÝ GIẤY PHÁ SẢN TRÓT LỌT!\n{user_name} đã giải thể '{biz['ten']}'. Bán tháo bàn ghế thu hồi được 50% vốn, tương đương {format_coin(refund)}."

    if cmd in ["/up", "/nangcap"]:
        if len(cmd_parts) != 2: return "❌ Cú pháp: /up [ID_Cửa_Hàng]. Dùng lệnh /taisan để xem ID."
        try: biz_id = int(cmd_parts[1])
        except: return "❌ ID cửa hàng không hợp lệ!"
        
        if user_name not in assets_data or not assets_data[user_name].get("businesses"):
            return "❌ Bạn trắng tay, làm gì có cơ sở kinh doanh nào mà đòi nâng cấp!"
            
        biz_list = assets_data[user_name]["businesses"]
        if biz_id < 0 or biz_id >= len(biz_list):
            return "❌ ID cửa hàng không tồn tại! Gõ /taisan để xem lại cho chuẩn."
            
        biz = biz_list[biz_id]
        cat_id = biz.get("id_nganh")
        current_qm_id = int(biz.get("id_quy_mo", 1))
        
        cat_info = None
        for key, info in business_config.items():
            if info.get("id_nganh") == cat_id:
                cat_info = info
                break
                
        if not cat_info:
            return "❌ Ngành kinh doanh này không còn tồn tại trong hệ thống!"
            
        next_qm_id = str(current_qm_id + 1)
        
        if next_qm_id not in cat_info['quy_mo']:
            return "❌ Cơ sở này đã đạt cấp độ (quy mô) TỐI ĐA! Không thể nâng cấp thêm."
            
        next_qm_info = cat_info['quy_mo'][next_qm_id]
        
        pf = get_profile(user_name, profile_data)
        used_management = 0.0
        for b in biz_list:
            b_qm_id = int(b.get("id_quy_mo", 1))
            if b.get("id_nganh") == "xd":
                used_management += 2 if b_qm_id <= 2 else 3
            else:
                used_management += 1 if b_qm_id <= 2 else 2
                
            used_management += b.get("employees", 0) * 0.5
                
        old_cost = 0; new_cost = 0
        if cat_id == "xd":
            old_cost = 2 if current_qm_id <= 2 else 3
            new_cost = 2 if int(next_qm_id) <= 2 else 3
        else:
            old_cost = 1 if current_qm_id <= 2 else 2
            new_cost = 1 if int(next_qm_id) <= 2 else 2
            
        management_diff = new_cost - old_cost
        
        if used_management + management_diff > pf["management_limit"]:
             return f"❌ Năng lực quản lý của bạn chỉ đạt {pf['management_limit']} điểm (Đang dùng {used_management} điểm).\nNâng cấp lên '{next_qm_info['ten']}' yêu cầu thêm {management_diff} điểm quản lý. Hãy gõ /docsach hoặc /hocdaihan để tăng IQ và mở rộng điểm!"
             
        upgrade_cost = next_qm_info['von'] - biz['von']
        balance = coin_data.get(user_name, 0)
        
        if balance < upgrade_cost:
            return f"❌ Thiếu vốn! Nâng cấp lên '{next_qm_info['ten']}' cần bù thêm {format_coin(upgrade_cost)}, bạn chỉ có {format_coin(balance)}."
            
        coin_data[user_name] -= upgrade_cost
        
        biz['id_quy_mo'] = next_qm_id
        biz['ten'] = next_qm_info['ten']
        biz['von'] = next_qm_info['von']
        biz['lai'] = next_qm_info['lai']
        biz['thoi_gian'] = next_qm_info['thoi_gian']
        
        save_json_data(COIN_FILE, coin_data)
        save_json_data(ASSETS_FILE, assets_data)
        
        return f"🚀 NÂNG CẤP THÀNH CÔNG!\n{user_name} đã chi {format_coin(upgrade_cost)} để nâng cấp lên '{next_qm_info['ten']}'.\nCơ sở sẽ tự động chốt đơn mang lại {format_coin(next_qm_info['lai'])} mỗi {format_time(next_qm_info['thoi_gian'])}!"

    # --- 👥 HỆ THỐNG TÍN DỤNG ĐEN P2P ---
    if msg.startswith("/chovay "):
        parts = message_text.split()
        if len(parts) < 5: return "❌ Cú pháp: /chovay @Tên [số_tiền] [%_lãi] [số_giờ]"
        try:
            hours = float(parts[-1])
            interest_rate = float(parts[-2])
            amt = int(parts[-3])
            
            if mentioned_names: target_name = mentioned_names[0]
            else: target_name = " ".join(parts[1:-3]).replace("*", "").replace("@", "").strip()
            
            target_name = find_exact_name(target_name, coin_data)
            
            if amt <= 0: return "❌ Tính lừa Tẻn à? Số_xu phải lớn hơn 0."
            if interest_rate < 0: return "❌ Bị điên à? Cho vay mà lãi âm?"
            if hours < 2: return "❌ Quy định chợ đen: Thời gian vay tối thiểu là 2 tiếng."
            if target_name.lower() == user_name.lower(): return "❌ Bị ảo tưởng à, tự cho mình vay?"
            
            balance = coin_data.get(user_name, 0)
            if balance < amt: return f"❌ Ra dẻ tỷ phú hả? Trong ví ông chỉ có {format_coin(balance)}."
            
            if target_name not in pending_p2p: pending_p2p[target_name] = {}
            pending_p2p[target_name][user_name] = {"amt": amt, "interest_rate": interest_rate, "hours": hours, "time": time.time()}
            
            return f"🤝 [HỢP ĐỒNG P2P] {user_name} muốn cho {target_name} vay {format_coin(amt)} (Lãi: {interest_rate}%, Hạn: {hours}h).\n👉 Này {target_name}, nếu đồng ý thì hãy Tag xác nhận bằng lệnh: '/nhanvay @{user_name}' trong vòng 5 phút nhé!"
        except ValueError:
            return "❌ Cú pháp sai! Ví dụ: /chovay @Huy 1000 10 2 (Cho Huy vay 1000 xu, lãi 10%, trả trong 2 giờ)"
            
    if msg.startswith("/nhanvay "):
        parts = message_text.split()
        if len(parts) < 2: return "❌ Cú pháp: /nhanvay @Tên_Người_Cho_Vay"
        
        if mentioned_names: lender_name = mentioned_names[0]
        else: lender_name = " ".join(parts[1:]).replace("*", "").replace("@", "").strip()
        
        lender_name = find_exact_name(lender_name, coin_data)
            
        actual_lender = None
        if user_name in pending_p2p:
            for ln in pending_p2p[user_name]:
                if ln.lower() == lender_name.lower(): actual_lender = ln; break
                    
        if actual_lender:
            req = pending_p2p[user_name][actual_lender]
            if time.time() - req["time"] > 300:
                del pending_p2p[user_name][actual_lender]
                return "❌ Hợp đồng này đã hết hạn (quá 5 phút). Kêu người ta /chovay lại đi."
                
            amt = req["amt"]
            lender_balance = coin_data.get(actual_lender, 0)
            if lender_balance < amt:
                del pending_p2p[user_name][actual_lender]
                return f"❌ {actual_lender} nổ cho cố vô giờ ví không đủ tiền cho vay rồi!"
                
            coin_data[actual_lender] -= amt
            coin_data[user_name] = coin_data.get(user_name, 0) + amt
            save_json_data(COIN_FILE, coin_data)
            
            total_debt = int(amt + (amt * req["interest_rate"] / 100))
            duration_secs = int(req["hours"] * 3600)
            
            if user_name not in p2p_data: p2p_data[user_name] = {}
            p2p_data[user_name][actual_lender] = {
                "principal": amt, "total": total_debt, "remaining": total_debt,
                "deadline": time.time() + duration_secs, "status": "ACTIVE", "notified": False, "seizable_time": 0
            }
            save_json_data(P2P_FILE, p2p_data)
            del pending_p2p[user_name][actual_lender]
            return f"💸 Giải ngân thành công! {user_name} đã nhận {format_coin(amt)} từ {actual_lender}.\n📉 Tổng nợ phải trả: {format_coin(total_debt)}. \n⏳ Thời hạn: Đúng {req['hours']} tiếng nữa!"
        return "❌ Có ma nào mời ông vay đâu mà đòi nhận?"
            
    if msg.startswith("/tratien "):
        parts = message_text.split()
        if len(parts) < 3: return "❌ Cú pháp: /tratien @Tên_Chủ_Nợ [số_tiền]"
        try:
            amt = int(parts[-1])
            if mentioned_names: lender_name = mentioned_names[0]
            else: lender_name = " ".join(parts[1:-1]).replace("*", "").replace("@", "").strip()
            
            lender_name = find_exact_name(lender_name, coin_data)
                
            if amt <= 0: return "❌ Tiền trả phải lớn hơn 0!"
            actual_lender = None
            if user_name in p2p_data:
                for ln in p2p_data[user_name]:
                    if ln.lower() == lender_name.lower(): actual_lender = ln; break
            if not actual_lender: return f"❌ Ông không nợ {lender_name} khoản P2P nào cả!"
            balance = coin_data.get(user_name, 0)
            if balance < amt: return f"❌ Chém gió à! Trong ví chỉ có {format_coin(balance)}."
            
            loan = p2p_data[user_name][actual_lender]
            take = min(amt, loan["remaining"])
            coin_data[user_name] -= take
            coin_data[actual_lender] = coin_data.get(actual_lender, 0) + take
            loan["remaining"] -= take
            save_json_data(COIN_FILE, coin_data)
            
            if loan["remaining"] <= 0:
                del p2p_data[user_name][actual_lender]
                if not p2p_data[user_name]: del p2p_data[user_name]
                save_json_data(P2P_FILE, p2p_data)
                return f"✅ Tốt lắm! {user_name} đã chuyển khoản trả {format_coin(take)} cho {actual_lender}. ĐÃ THANH TOÁN SẠCH NỢ P2P!"
            save_json_data(P2P_FILE, p2p_data)
            return f"✅ {user_name} đã chuyển khoản {format_coin(take)} cho {actual_lender}. Còn nợ: {format_coin(loan['remaining'])}."
        except ValueError: return "❌ Số tiền trả không hợp lệ."
            
    if msg.startswith("/sietno "):
        parts = message_text.split()
        if len(parts) < 2: return "❌ Cú pháp: /sietno @Tên_Con_Nợ"
        
        if mentioned_names: borrower_name = mentioned_names[0]
        else: borrower_name = " ".join(parts[1:]).replace("*", "").replace("@", "").strip()
        
        borrower_name = find_exact_name(borrower_name, coin_data)
            
        actual_borrower = None
        for b in p2p_data:
            if b.lower() == borrower_name.lower() and user_name in p2p_data[b]:
                actual_borrower = b; break
                
        if actual_borrower:
            loan = p2p_data[actual_borrower][user_name]
            if loan["status"] != "SEIZABLE": return f"❌ Láo nháo à! Chưa đến hạn trả nợ hoặc chưa hết 5 phút ân hạn, không được xách mã tấu đi siết!"
                
            remaining = loan["remaining"]
            borrower_balance = coin_data.get(actual_borrower, 0)
            
            take_cash = 0
            if borrower_balance > 10:
                take_cash = int(borrower_balance * 0.85)
                if take_cash > remaining: take_cash = remaining
            if take_cash > 0:
                coin_data[actual_borrower] -= take_cash
                coin_data[user_name] = coin_data.get(user_name, 0) + take_cash
                remaining -= take_cash
                
            # Siết Vàng P2P
            seized_gold_msg = ""
            if remaining > 0 and actual_borrower in gold_data:
                gp = get_gold_prices()
                if gp:
                    u_gold = gold_data[actual_borrower]
                    for g_type, g_price in [("nhan", gp.get("nhan_mua", 0)), ("mieng", gp.get("mieng_mua", 0))]:
                        g_taken = 0
                        while remaining > 0 and u_gold.get(g_type, 0) > 0:
                            u_gold[g_type] -= 1
                            g_taken += 1
                            if g_price >= remaining:
                                refund = g_price - remaining
                                coin_data[user_name] = coin_data.get(user_name, 0) + remaining
                                coin_data[actual_borrower] = coin_data.get(actual_borrower, 0) + refund
                                remaining = 0
                            else:
                                remaining -= g_price
                                coin_data[user_name] = coin_data.get(user_name, 0) + g_price
                        if g_taken > 0:
                            g_name = "Vàng Nhẫn" if g_type == "nhan" else "Vàng Miếng"
                            seized_gold_msg += f"🪙 Tịch thu {g_taken} lượng {g_name}.\n"
                    save_json_data(GOLD_FILE, gold_data)

            # Siết Cửa hàng P2P
            seized_biz = []
            refund = 0
            if remaining > 0 and actual_borrower in assets_data and assets_data[actual_borrower].get("businesses"):
                assets = assets_data[actual_borrower]["businesses"]
                assets.sort(key=lambda x: x["von"]) 
                while remaining > 0 and assets:
                    biz = assets.pop(0)
                    seized_biz.append(biz)
                    biz_val = biz["von"]
                    if biz_val >= remaining:
                        refund = biz_val - remaining
                        coin_data[user_name] = coin_data.get(user_name, 0) + remaining
                        coin_data[actual_borrower] = coin_data.get(actual_borrower, 0) + refund
                        remaining = 0
                    else:
                        remaining -= biz_val
                        coin_data[user_name] = coin_data.get(user_name, 0) + biz_val
                assets_data[actual_borrower]["businesses"] = assets
                save_json_data(ASSETS_FILE, assets_data)
            
            loan["remaining"] = remaining
            save_json_data(COIN_FILE, coin_data)
            
            msg_res = f"🪓 BIÊN BẢN SIẾT NỢ: {user_name} (CHỦ) vs {actual_borrower} (NỢ) 🪓\n"
            if take_cash > 0: msg_res += f"💵 Thu tiền mặt (85% ví): {format_coin(take_cash)}.\n"
            else: msg_res += f"💵 Trong ví con nợ <= 10 xu (Tạm tha mạng cho sống sót).\n"
            if seized_gold_msg: msg_res += seized_gold_msg
            if seized_biz:
                biz_names = ", ".join([b["ten"] for b in seized_biz])
                msg_res += f"🏢 Tịch thu cơ sở kinh doanh: {biz_names}.\n"
                if refund > 0: msg_res += f"⚖️ Thối lại cho con nợ {format_coin(refund)}.\n"
                
            if remaining <= 0:
                msg_res += f"✅ ĐÃ ÉP TRẢ SẠCH NỢ! Xé giấy nợ."
                del p2p_data[actual_borrower][user_name]
                if not p2p_data[actual_borrower]: del p2p_data[actual_borrower]
            else:
                msg_res += f"📉 Siết sạch sành sanh mà vẫn không đủ. Nợ còn đọng lại: {format_coin(remaining)}."
            save_json_data(P2P_FILE, p2p_data)
            return msg_res
        return f"❌ {borrower_name} không nợ ông đồng nào, hoặc ông gõ sai tên nó rồi!"

    if msg.startswith("/chuyenxu "):
        parts = message_text.split(" ")
        if len(parts) >= 3:
            try:
                amount = int(parts[-1])
                if mentioned_names: target_name = mentioned_names[0]
                else: target_name = " ".join(parts[1:-1]).replace("*", "").replace("@", "").strip()
                
                target_name = find_exact_name(target_name, coin_data)
                    
                if amount <= 0: return "Lỗi số âm!"
                if coin_data.get(user_name, 0) < amount: return f"❌ {user_name} không đủ tiền!"
                coin_data[user_name] -= amount
                coin_data[target_name] = coin_data.get(target_name, 0) + amount
                save_json_data(COIN_FILE, coin_data)
                return f"💸 {user_name} đã chuyển {format_coin(amount)} cho {target_name}."
            except: return "Lỗi định dạng."
        return "Cú pháp: /chuyenxu @Tên Số_Xu"

    if cmd in ["/khoinghiep", "/kn"]:
        if len(cmd_parts) == 1:
            res = "🏢 DANH MỤC ĐẦU TƯ KHỞI NGHIỆP 🏢\n\n"
            for k, v in business_config.items():
                res += f"{k}. Mở {v['ten_nganh']} (Lệnh: /kn {k})\n"
            res += "\n👉 Gõ '/kn [số]' để xem chi tiết quy mô đầu tư của ngành đó."
            return res
        elif len(cmd_parts) == 2:
            cat_id = cmd_parts[1]
            if cat_id in business_config:
                cat_info = business_config[cat_id]
                res = f"📊 QUY MÔ: {cat_info['ten_nganh'].upper()}\n\n"
                for qm_id, qm_info in cat_info['quy_mo'].items():
                    res += f"{qm_id}. {qm_info['ten']} - Vốn: {format_coin(qm_info['von'])}\n"
                    res += f"   (Thu nhập: {format_coin(qm_info['lai'])} / {format_time(qm_info['thoi_gian'])})\n"
                res += f"\n👉 Để mua, gõ '/{cat_info['id_nganh']} [số quy mô]'. Ví dụ: /{cat_info['id_nganh']} 1"
                return res
            return "❌ Không có ngành kinh doanh này trong danh mục!"

    for cat_id, cat_info in business_config.items():
        if cmd == f"/{cat_info['id_nganh']}":
            if len(cmd_parts) != 2: return f"❌ Sai cú pháp. Gõ '/{cat_info['id_nganh']} [số quy mô]'. Ví dụ: /{cat_info['id_nganh']} 1"
            qm_id = cmd_parts[1]
            if qm_id not in cat_info['quy_mo']: return "❌ Quy mô này không tồn tại! Gõ /kn để xem lại."
            qm_info = cat_info['quy_mo'][qm_id]
            cost = qm_info['von']
            balance = coin_data.get(user_name, 0)
            if balance < cost: return f"❌ Bạn không đủ vốn! Cần {format_coin(cost)} để mở '{qm_info['ten']}', bạn chỉ có {format_coin(balance)}."
            
            # Check Management Limit
            pf = get_profile(user_name, profile_data)
            used_management = 0.0
            if user_name in assets_data and assets_data[user_name].get("businesses"):
                for b in assets_data[user_name]["businesses"]:
                    b_qm_id = int(b.get("id_quy_mo", 1))
                    if b.get("id_nganh") == "xd":
                        used_management += 2 if b_qm_id <= 2 else 3
                    else:
                        used_management += 1 if b_qm_id <= 2 else 2
                    used_management += b.get("employees", 0) * 0.5
            
            new_cost = 0
            if cat_info['id_nganh'] == "xd": new_cost = 2 if int(qm_id) <= 2 else 3
            else: new_cost = 1 if int(qm_id) <= 2 else 2
            
            if used_management + new_cost > pf["management_limit"]:
                return f"❌ Năng lực quản lý của bạn chỉ đạt {pf['management_limit']} điểm (Đang dùng {used_management}).\nMô hình '{qm_info['ten']}' yêu cầu {new_cost} điểm quản lý. Hãy gõ /docsach hoặc /hocdaihan để tăng IQ và mở rộng khả năng quản lý!"

            coin_data[user_name] -= cost
            save_json_data(COIN_FILE, coin_data)
            if user_name not in assets_data: assets_data[user_name] = {"businesses": []}
            new_business = {"id_nganh": cat_info['id_nganh'], "id_quy_mo": qm_id, "ten": qm_info['ten'], "von": cost, "lai": qm_info['lai'], "thoi_gian": qm_info['thoi_gian'], "last_payout": time.time()}
            assets_data[user_name]["businesses"].append(new_business)
            save_json_data(ASSETS_FILE, assets_data)
            return f"🎉 CHÚC MỪNG ÔNG CHỦ! {user_name} đã khai trương thành công '{qm_info['ten']}'.\nCứ mỗi {format_time(qm_info['thoi_gian'])}, hệ thống sẽ tự động gửi tiền lãi vào ví!"

    if msg == "/altp":
        if user_name in altp_games: return f"❌ {user_name} đang bận quay Ai Là Triệu Phú rồi, tập trung đi!"
        
        current_day = get_tarot_day()
        if altp_winners_data.get(user_name) == current_day:
            return f"🏆 Chói lóa quá! {user_name} đã ẵm giải 100.000 xu phá đảo chương trình trong ngày hôm nay rồi. Nhà đài xin từ chối phục vụ để tránh phá sản, ngày mai quay lại nhé!"
            
        balance = coin_data.get(user_name, 0)
        if balance < 50:
            return f"❌ Nghèo! {user_name} cần 50 xu để mua vé tham gia Ai Là Triệu Phú nhưng trong ví chỉ có {format_coin(balance)}."
            
        coin_data[user_name] -= 50
        save_json_data(COIN_FILE, coin_data)
        
        altp_games[user_name] = {"state": "WAITING_START", "end_time": time.time() + 60}
        res = f"💸 Đã trừ 50 xu lệ phí thi.\n🔥 CHÀO MỪNG {user_name} ĐẾN VỚI TRƯỜNG QUAY AI LÀ TRIỆU PHÚ 🔥\n\n"
        res += "📜 LUẬT CHƠI:\n- Vượt qua 15 câu để giật giải 100.000 xu.\n- 2 mốc an toàn: Câu 5 (1.000 xu), Câu 10 (20.000).\n- Thời gian: Tốc độ bàn thờ 25s/câu! Cấm tra Google.\n\n"
        res += "💡 QUYỀN TRỢ GIÚP (1 lần/game, +30s):\n1. /5050 (Bỏ 2 đáp án sai)\n2. /gdnt (Gọi điện thoại người thân)\n3. /ntt (Hỏi nhà thông thái)\n\n"
        res += "👉 Trạng thái tâm lý ổn định chưa? Gõ '/ss' để BẮT ĐẦU hoặc '/css' để THOÁT trong vòng 60 giây."
        return res

    if msg == "/css":
        if user_name in altp_games and altp_games[user_name]["state"] == "WAITING_START":
            del altp_games[user_name]
            coin_data[user_name] = coin_data.get(user_name, 0) + 50
            save_json_data(COIN_FILE, coin_data)
            return f"🛑 Trống ngực đập thình thịch à? {user_name} đã xin phép rời khỏi trường quay và được hoàn lại 50 xu vé vào cửa."

    if msg == "/ss":
        if user_name in altp_games and altp_games[user_name]["state"] == "WAITING_START":
            questions = load_altp_questions()
            if len(questions) < 15: return "❌ Ngân hàng câu hỏi chưa đủ 15 câu. Hãy báo Admin nạp thêm file altp_questions.json!"
            game_questions = random.sample(questions, 15)
            question = game_questions[0]
            altp_games[user_name] = {"step": 1, "q_list": game_questions, "q_data": question, "lifelines": {"5050": True, "gdnt": True, "ntt": True}, "end_time": time.time() + 25, "state": "PLAYING"}
            
            avatar_url = user_avatars.get(user_name, "")
            img_path = tao_anh_altp(user_name, 1, ALTP_PRIZES[1], question, altp_games[user_name]["lifelines"], avatar_url)
            caption = "🎬 ÁNH SÁNG, ÂM THANH! CHÚNG TA BẮT ĐẦU!\n⏳ Gõ /a, /b, /c, /d để trả lời (Bạn có 25s)."
            return {"type": "image", "path": img_path, "caption": caption}

    if msg in ["/a", "/b", "/c", "/d"]:
        if user_name not in altp_games or altp_games[user_name]["state"] != "PLAYING": return None
        game = altp_games[user_name]
        ans = msg[1] 
        correct_ans = game["q_data"]["ans"]
        step = game["step"]
        if ans == correct_ans:
            prize = ALTP_PRIZES[step]
            if step == 15:
                coin_data[user_name] = coin_data.get(user_name, 0) + prize
                save_json_data(COIN_FILE, coin_data)
                del altp_games[user_name]
                altp_winners_data[user_name] = get_tarot_day()
                save_json_data(ALTP_WINNERS_FILE, altp_winners_data)
                pf = get_profile(user_name, profile_data)
                pf["stress"] = max(0, pf.get("stress", 0) - 25)
                save_json_data(PROFILE_FILE, profile_data)
                return f"🎉 KHÔNG THỂ TIN NỔI! CHÚC MỪNG {user_name} TRỞ THÀNH TRIỆU PHÚ! 💰 Nhận ngay {format_coin(prize)}! (Stress -25)"
                
            if step in [5, 10]:
                game["state"] = "MILESTONE_ASK"
                game["end_time"] = time.time() + 99999 
                return f"✅ CHÍNH XÁC! {user_name} vượt qua câu {step} và đạt MỐC AN TOÀN {format_coin(prize)}.\n\n👉 Bạn có muốn chơi tiếp không? Gõ '/choitiep' để khô máu, hoặc '/dunglai' để cầm tiền về."

            game["step"] += 1
            new_q = game["q_list"][game["step"] - 1]
            game["q_data"] = new_q
            game["end_time"] = time.time() + 25
            next_prize = ALTP_PRIZES[game["step"]]
            
            avatar_url = user_avatars.get(user_name, "")
            img_path = tao_anh_altp(user_name, game["step"], next_prize, new_q, game["lifelines"], avatar_url)
            caption = f"✅ CHÍNH XÁC! Bạn tích lũy được {format_coin(prize)}.\n⏳ Bạn có 25s để trả lời câu tiếp theo."
            return {"type": "image", "path": img_path, "caption": caption}
        else:
            safe_prize = 0
            if step > 10: safe_prize = 20000
            elif step > 5: safe_prize = 1000
            if safe_prize > 0:
                coin_data[user_name] = coin_data.get(user_name, 0) + safe_prize
                save_json_data(COIN_FILE, coin_data)
            del altp_games[user_name]
            
            pf = get_profile(user_name, profile_data)
            pf["stress"] = max(0, pf.get("stress", 0) - 25)
            save_json_data(PROFILE_FILE, profile_data)
            
            res = f"❌ RẤT TIẾC, ĐÁP ÁN ĐÚNG LÀ {correct_ans.upper()}!\n💆 Dù sao chơi gameshow xong Stress nắp lại cũng giảm 25 điểm.\n"
            if safe_prize > 0: res += f"💰 Bạn ra về với tiền thưởng mốc an toàn: {format_coin(safe_prize)}."
            else: res += f"💸 Trắng tay mất rồi! {random.choice(ALTP_LOSE_MESSAGES)}"
            return res

    if msg == "/dunglai":
        if user_name in altp_games and altp_games[user_name]["state"] == "MILESTONE_ASK":
            prize = ALTP_PRIZES[altp_games[user_name]["step"]]
            coin_data[user_name] = coin_data.get(user_name, 0) + prize
            save_json_data(COIN_FILE, coin_data)
            del altp_games[user_name]
            
            pf = get_profile(user_name, profile_data)
            pf["stress"] = max(0, pf.get("stress", 0) - 25)
            save_json_data(PROFILE_FILE, profile_data)
            
            return f"🛑 Biết điểm dừng là thông minh! {user_name} bảo toàn được {format_coin(prize)}.\n💆 Chơi xong giải trí xả láng, Stress giảm 25 điểm."
            
    if msg == "/choitiep":
        if user_name in altp_games and altp_games[user_name]["state"] == "MILESTONE_ASK":
            game = altp_games[user_name]
            game["step"] += 1
            new_q = game["q_list"][game["step"] - 1]
            game["q_data"] = new_q
            game["end_time"] = time.time() + 25 
            game["state"] = "PLAYING"
            next_prize = ALTP_PRIZES[game["step"]]
            
            avatar_url = user_avatars.get(user_name, "")
            img_path = tao_anh_altp(user_name, game["step"], next_prize, new_q, game["lifelines"], avatar_url)
            caption = f"🔥 Rất bản lĩnh! Cuộc chơi tiếp tục!\n⏳ Bạn có 25s để trả lời."
            return {"type": "image", "path": img_path, "caption": caption}

    if msg in ["/50:50", "/5050", "/gdnt", "/ntt"]:
        if user_name not in altp_games or altp_games[user_name]["state"] != "PLAYING": return None
        game = altp_games[user_name]
        q_data = game["q_data"]
        correct_ans = q_data["ans"]
        options = ["a", "b", "c", "d"]
        options.remove(correct_ans)
        avatar_url = user_avatars.get(user_name, "")
        
        if msg in ["/50:50", "/5050"]:
            if not game["lifelines"]["5050"]: return "❌ Máy tính báo lỗi! Bạn đã xài quyền 50:50 rồi."
            game["lifelines"]["5050"] = False; game["end_time"] += 30
            wrong_ans = random.choice(options); remain = [correct_ans, wrong_ans]; random.shuffle(remain)
            
            # Tạo data ảo với 2 đáp án bị loại bỏ để vẽ ảnh
            display_q = {"q": q_data["q"], "opts": {}}
            for opt in ["a", "b", "c", "d"]:
                if opt in remain: display_q["opts"][opt] = q_data["opts"][opt]
                else: display_q["opts"][opt] = "[Đã loại bỏ]"
                
            img_path = tao_anh_altp(user_name, game["step"], ALTP_PRIZES[game["step"]], display_q, game["lifelines"], avatar_url)
            caption = "🪄 Máy tính đã loại bỏ 2 phương án sai!\n⏳ Thời gian của bạn được cộng thêm 30 giây."
            return {"type": "image", "path": img_path, "caption": caption}
            
        elif msg == "/gdnt":
            if not game["lifelines"]["gdnt"]: return "❌ Điện thoại hết tiền rồi, đã gọi người thân từ trước đó!"
            game["lifelines"]["gdnt"] = False; game["end_time"] += 30
            relative = random.choice(["mẹ của bạn", "bố của bạn", "anh trai của bạn", "chị gái của bạn", "ông chú làm Viettel", "thằng bạn chí cốt", "con nợ của bạn"])
            suggested = correct_ans if random.randint(1, 100) <= 95 else random.choice(options)
            phrases = [
                f"Alo con à, câu này dễ òm, chọn {suggested.upper()} đi con!",
                f"Trời ơi đang bận, {suggested.upper()} nha, cúp máy đây tút tút...",
                f"Tao vừa tra Google rồi, 100% là {suggested.upper()} mày ơi!",
                f"Câu này nhà mình ai chả biết, quất ngay {suggested.upper()} nhé!",
                f"Tin tao, đáp án là {suggested.upper()}. Chơi tới bến đi!"
            ]
            
            img_path = tao_anh_altp(user_name, game["step"], ALTP_PRIZES[game["step"]], q_data, game["lifelines"], avatar_url)
            caption = f"📞 Đã kết nối với {relative}...\n🗣️ {relative}: \"{random.choice(phrases)}\"\n\n⏳ Thời gian được cộng thêm 30 giây."
            return {"type": "image", "path": img_path, "caption": caption}
            
        elif msg == "/ntt":
            if not game["lifelines"]["ntt"]: return "❌ Các nhà thông thái đi ngủ hết rồi, bạn đã dùng quyền này rồi!"
            game["lifelines"]["ntt"] = False; game["end_time"] += 30
            scholar = random.choice(["Nhà vật lý học Albert Einstein", "Nhà toán học Ngô Bảo Châu", "Giáo sư Xoay", "Nhà bác học Isaac Newton", "Danh hài Mạc Văn Khoa"])
            suggested = correct_ans if random.randint(1, 100) <= 95 else random.choice(options)
            phrases = [
                f"Dựa trên các nghiên cứu của tôi, đáp án chính xác là {suggested.upper()}.",
                f"Tôi đã phân tích rất kỹ, bạn hãy mạnh dạn chọn phương án {suggested.upper()}.",
                f"Bằng linh cảm của một vĩ nhân, tôi chốt đáp án {suggested.upper()}.",
                f"Câu này nhắm mắt tôi cũng chọn {suggested.upper()}!"
            ]
            
            img_path = tao_anh_altp(user_name, game["step"], ALTP_PRIZES[game["step"]], q_data, game["lifelines"], avatar_url)
            caption = f"🧠 {scholar} đã vào phòng chat...\n🗣️ {scholar}: \"{random.choice(phrases)}\"\n\n⏳ Thời gian được cộng thêm 30 giây."
            return {"type": "image", "path": img_path, "caption": caption}

    if msg in ["/lamruong", "/danhca", "/xeom", "/vechai"]:
        if user_name in jobs_data:
            job_info = jobs_data[user_name]
            rem_time = int(job_info["end_time"] - time.time())
            if rem_time > 0: return f"❌ Ê từ từ! {user_name} đang bận đi '{job_info['job_name']}' rồi!\n⏳ Ráng đợi {format_time(rem_time)} nữa nha!"
        
        pf = get_profile(user_name, profile_data)
        if pf.get("training") and pf["training"]["end_time"] > time.time():
            return f"❌ {user_name} đang bận {pf['training']['type']} rồi, sức đâu mà đi làm nữa!"

        if msg == "/lamruong": cost, reward, duration, jname, hp_cost = 20, 200, 300, "Làm ruộng 🌾", 10; dur_str = "5 phút"
        elif msg == "/danhca": cost, reward, duration, jname, hp_cost = 10, 100, 300, "Đánh cá 🐟", 8; dur_str = "5 phút"
        elif msg == "/xeom": cost, reward, duration, jname, hp_cost = 50, 400, 1800, "Chạy xe ôm 🏍️", 15; dur_str = "30 phút"
        elif msg == "/vechai": cost, reward, duration, jname, hp_cost = 5, 30, 180, "Nhặt ve chai 🗑️", 5; dur_str = "3 phút"
        
        balance = coin_data.get(user_name, 0)
        if balance < cost: return f"❌ Nghèo mạt rệp! Không đủ {cost} xu tiền vốn để đi {jname}!"
        
        if pf["health"] < hp_cost:
            # Sự kiện xấu thay vì làm việc
            pf["health"] = 0
            pf["stress"] = min(100, pf.get("stress", 0) + 5)
            save_json_data(PROFILE_FILE, profile_data)
            penalty_coin = min(balance, random.randint(50, 150))
            if penalty_coin > 0:
                coin_data[user_name] -= penalty_coin
                save_json_data(COIN_FILE, coin_data)
            return f"🚑 OÉT OÉT! {user_name} cố xách xác đi {jname} khi sức khỏe cạn kiệt (<{hp_cost}) nên ngất xỉu dọc đường!\n💸 Đi cấp cứu tốn mất {penalty_coin} xu và Stress tăng 5 điểm! Hãy nghỉ ngơi đi."

        pf["health"] -= hp_cost
        save_json_data(PROFILE_FILE, profile_data)
        coin_data[user_name] -= cost
        save_json_data(COIN_FILE, coin_data)
        jobs_data[user_name] = {"job_name": jname, "reward": reward, "end_time": time.time() + duration}
        save_json_data(JOBS_FILE, jobs_data)
        return f"💼 {user_name} đã đầu tư {cost} xu làm vốn đi {jname} (Tốn {hp_cost} Sức khỏe. SK còn: {pf['health']}).\n⏳ Hãy nghỉ ngơi, đúng {dur_str} nữa sẽ có lương!"

    if msg in ["/chaybo", "/tapgym"]:
        pf = get_profile(user_name, profile_data)
        if pf.get("training") and pf["training"]["end_time"] > time.time():
            return f"❌ {user_name} đang bận {pf['training']['type']} rồi!"
        if user_name in jobs_data and jobs_data[user_name]["end_time"] > time.time():
            return f"❌ {user_name} đang đi làm thuê, thời gian đâu mà rèn luyện thể chất!"

        if msg == "/chaybo": type_name, hp_cost, time_cost, coin_cost, limit_boost = "chạy bộ", 4, 1800, 0, 2
        else: type_name, hp_cost, time_cost, coin_cost, limit_boost = "tập gym", 10, 5400, 250, 5

        if coin_data.get(user_name, 0) < coin_cost:
            return f"❌ Không đủ {coin_cost} xu để đăng ký {type_name}!"
        if pf["health"] < hp_cost:
            return f"❌ Không đủ Sức khỏe để {type_name}! Cần {hp_cost} SK nhưng bạn chỉ còn {pf['health']} SK."

        if coin_cost > 0:
            coin_data[user_name] -= coin_cost
            save_json_data(COIN_FILE, coin_data)
            
        pf["health"] -= hp_cost
        pf["training"] = {
            "type": type_name,
            "end_time": time.time() + time_cost,
            "boost": limit_boost
        }
        save_json_data(PROFILE_FILE, profile_data)
        return f"🏃 BẮT ĐẦU ĐỔ MỒ HÔI! {user_name} đã đi {type_name} (Tốn {hp_cost} Sức khỏe, {coin_cost}).\n⏳ Vui lòng đợi {format_time(time_cost)} để rèn luyện xong và tăng giới hạn Sức khỏe!"

    if msg in ["/uongnuoc", "/uongnuoctangluc", "/tamsuoi", "/tamsuoinong"]:
        if msg in ["/uongnuoc", "/uongnuoctangluc"]: item_name, hp_heal, coin_cost = "uống nước tăng lực 🔋", 2, 20
        else: item_name, hp_heal, coin_cost = "tắm suối nước nóng ♨️", 10, 200
        
        balance = coin_data.get(user_name, 0)
        if balance < coin_cost:
            return f"❌ Nghèo! {user_name} cần {coin_cost} xu để {item_name}!"
            
        pf = get_profile(user_name, profile_data)
        if pf["health"] >= pf["max_health"]:
            return f"❌ Sức khỏe của {user_name} đang ở mức tối đa ({pf['max_health']}), không cần {item_name} nữa đâu!"
            
        coin_data[user_name] -= coin_cost
        save_json_data(COIN_FILE, coin_data)
        
        pf["health"] = min(pf["health"] + hp_heal, pf["max_health"])
        save_json_data(PROFILE_FILE, profile_data)
        
        return f"💆 Hồi phục sinh lực! {user_name} đã chi {coin_cost} xu để {item_name}.\n❤️ Sức khỏe tăng thêm {hp_heal} điểm (SK hiện tại: {pf['health']}/{pf['max_health']})."

    if msg in ["/docsach", "/lambaitest", "/hocnangcao", "/hocdaihan"]:
        pf = get_profile(user_name, profile_data)
        
        if msg == "/docsach":
            # Cooldown đọc sách 5 phút
            last_read = pf.get("last_read", 0)
            if time.time() - last_read < 300:
                return f"❌ Đọc nhiều lòi mắt đấy! Chờ thêm {format_time(int(300 - (time.time() - last_read)))} nữa mới được đọc cuốn tiếp theo."
            pf["iq"] += 0.01
            pf["last_read"] = time.time()
            save_json_data(PROFILE_FILE, profile_data)
            return f"📚 🤓 {user_name} vừa thẩm thấu tri thức từ một cuốn sách hay. IQ tăng nhẹ lên {pf['iq']:.2f}!"
            
        if msg == "/lambaitest": cost, iq_gain, stress_gain, tname = 50, 0.05, 1, "Làm bài test 📝"
        elif msg == "/hocnangcao": cost, iq_gain, stress_gain, tname = 200, 0.1, 3, "Học lớp nâng cao 🎓"
        elif msg == "/hocdaihan": cost, iq_gain, stress_gain, tname = 500, 0.5, 10, "Khóa học dài hạn 🏫"
        
        balance = coin_data.get(user_name, 0)
        if balance < cost:
            return f"❌ Xin lỗi, học phí cho '{tname}' là {cost}. Bạn đang có {format_coin(balance)}."
            
        coin_data[user_name] -= cost
        save_json_data(COIN_FILE, coin_data)
        pf["iq"] += iq_gain
        pf["stress"] = min(100, pf.get("stress", 0) + stress_gain)
        save_json_data(PROFILE_FILE, profile_data)
        return f"🎓 {user_name} đã đăng ký '{tname}' (Tốn {cost}).\n🧠 Trí tuệ mở mang! IQ vĩnh viễn tăng thêm {iq_gain} lên mức {pf['iq']:.2f}.\n😫 Căng thẳng tăng thêm {stress_gain} điểm (Stress: {pf['stress']}/100)."

    if msg.startswith("/vay "):
        parts = message_text.split()
        if len(parts) != 2: return "❌ Cú pháp: /vay [số_tiền]"
        try:
            amt = int(parts[1])
            credit = credit_data.get(user_name, 0)
            max_loan = 2000 + (credit * 200)
            if amt <= 0: return "❌ Nhập số tào lao tính lừa Tẻn à?"
            if amt > max_loan: return f"❌ Điểm uy tín của {user_name} là {credit}, nên Tẻn chỉ cho vay tối đa {format_coin(max_loan)} thôi!"
            
            # Kiểm tra ví bot còn đủ tiền không
            bot_balance = coin_data.get(BOT_NAME, BOT_DEFAULT_BALANCE)
            if bot_balance < amt:
                return f"❌ Tẻn cũng hết tiền rồi! Ví Tẻn hiện chỉ còn {format_coin(bot_balance)}, không đủ cho {user_name} mượn {format_coin(amt)} đâu!"
            
            if user_name in loan_data:
                loan_info = loan_data[user_name]
                if loan_info.get("loan_count", 1) >= 2: return f"❌ Mạt vận! {user_name} đang gánh 2 bát họ trên vai rồi!"
                interest_2 = int(amt * 0.22); total_new_debt = amt + interest_2
                pending_loans[user_name] = {"amt": amt, "total_new_debt": total_new_debt, "time": time.time()}
                res = f"⚠️ [CẢNH BÁO BỐC HỌ LẦN 2] ⚠️\n{user_name} đang ôm cục nợ {format_coin(loan_info['remaining'])}. Khoản mới lãi 22% nhé!\n"
                res += f"👉 Vay {format_coin(amt)} -> Lãi+Gốc: {format_coin(total_new_debt)}.\n👉 Gõ '/dongy' trong 60s để chốt sổ!"
                return res
            interest = int(amt * 0.20); total_debt = amt + interest
            # Xuất tiền từ ví bot → ví người dùng
            coin_data[BOT_NAME] = bot_balance - amt
            coin_data[user_name] = coin_data.get(user_name, 0) + amt
            save_json_data(COIN_FILE, coin_data)
            loan_data[user_name] = {"principal": amt, "total": total_debt, "remaining": total_debt, "loan_count": 1, "deadline": time.time() + 7200, "warned": False, "seizing": False, "last_seize_time": 0}
            save_json_data(LOAN_FILE, loan_data)
            return f"💸 {user_name} đã bốc bát họ {format_coin(amt)} thành công!\n📉 Lãi 20%. Tổng nợ: {format_coin(total_debt)}.\n⏳ Hạn: 2 tiếng nữa."
        except ValueError: return "❌ Số_xu vay không hợp lệ!"
            
    if msg == "/dongy":
        if user_name in pending_loans:
            if time.time() - pending_loans[user_name]["time"] <= 60:
                amt = pending_loans[user_name]["amt"]
                new_debt = pending_loans[user_name]["total_new_debt"]
                # Kiểm tra ví bot
                bot_balance = coin_data.get(BOT_NAME, BOT_DEFAULT_BALANCE)
                if bot_balance < amt:
                    del pending_loans[user_name]
                    return f"❌ Tẻn vừa cạn ví! Không đủ {format_coin(amt)} để giải ngân khoản 2 cho {user_name}."
                coin_data[BOT_NAME] = bot_balance - amt
                coin_data[user_name] = coin_data.get(user_name, 0) + amt
                save_json_data(COIN_FILE, coin_data)
                loan_info = loan_data[user_name]
                loan_info["principal"] += amt; loan_info["total"] += new_debt; loan_info["remaining"] += new_debt
                loan_info["loan_count"] = 2; loan_info["deadline"] = time.time() + 7200 
                save_json_data(LOAN_FILE, loan_data); del pending_loans[user_name]
                return f"💸 Đã giải ngân khoản vay thứ 2: {format_coin(amt)}.\n📈 Tổng nợ dồn: {format_coin(loan_info['remaining'])}. Hạn chót reset thành 2 tiếng!"
            else: del pending_loans[user_name]; return f"❌ Quá 60s, hủy vay lần 2 của {user_name}."
        return f"❌ {user_name} không có khoản vay chờ duyệt."

    if msg.startswith("/tra "):
        parts = message_text.split()
        if len(parts) != 2: return "❌ Cú pháp: /tra [số_tiền]"
        if user_name not in loan_data: return f"❌ {user_name} không nợ đồng nào mà cũng đòi trả à?"
        try:
            amt = int(parts[1])
            if amt <= 0: return "❌ Tiền trả không hợp lệ!"
            balance = coin_data.get(user_name, 0)
            if balance < amt: return f"❌ Trong ví {user_name} chỉ có {format_coin(balance)}."
            loan = loan_data[user_name]
            take = min(amt, loan["remaining"])
            coin_data[user_name] -= take; loan["remaining"] -= take
            # Hoàn tiền về ví bot
            coin_data[BOT_NAME] = coin_data.get(BOT_NAME, BOT_DEFAULT_BALANCE) + take
            extension_seconds = (take / loan["total"]) * 7200 
            loan["deadline"] = max(loan["deadline"], time.time()) + extension_seconds
            loan["warned"] = False; loan["seizing"] = False
            save_json_data(COIN_FILE, coin_data)
            if loan["remaining"] <= 0:
                del loan_data[user_name]; save_json_data(LOAN_FILE, loan_data)
                credit_data[user_name] = credit_data.get(user_name, 0) + 10; save_json_data(CREDIT_FILE, credit_data)
                return f"✅ Tẻn đã nhận {format_coin(take)}. {user_name} đã TRẢ HẾT NỢ!\n🌟 Thưởng: +10 Uy tín!"
            save_json_data(LOAN_FILE, loan_data)
            return f"✅ Đã thu {format_coin(take)}. {user_name} còn nợ: {format_coin(loan['remaining'])}.\n⏳ Gia hạn thêm {int(extension_seconds/60)} phút."
        except ValueError: return "❌ Lỗi số tiền."

    if msg.startswith("/veso "):
        parts = message_text.split()
        if len(parts) != 2: return "❌ Cú pháp: /veso [số_lượng]"
        try:
            amount = int(parts[1])
            if amount <= 0 or amount > 100: return "❌ Số vé từ 1 đến 100!"
            cost = amount * 10
            balance = coin_data.get(user_name, 0)
            if balance < cost: return f"❌ {user_name} không đủ {format_coin(cost)}!"
            coin_data[user_name] -= cost
            jackpot, first, second, cons, lose, total_win = 0, 0, 0, 0, 0, 0
            for _ in range(amount):
                roll = random.randint(1, 1000)
                if roll <= 2: jackpot += 1; total_win += 1000
                elif roll <= 12: first += 1; total_win += 200
                elif roll <= 52: second += 1; total_win += 50
                elif roll <= 202: cons += 1; total_win += 10
                else: lose += 1
            coin_data[user_name] += total_win; save_json_data(COIN_FILE, coin_data)
            res = f"🎫 {user_name} đã cào {amount} vé (Tốn {cost}):\n"
            if jackpot > 0: res += f"💎 ĐỘC ĐẮC (1000x): {jackpot}\n"
            if first > 0: res += f"🥇 Giải 1 (200x): {first}\n"
            if second > 0: res += f"🥈 Giải 2 (50x): {second}\n"
            if cons > 0: res += f"🥉 KK (10x): {cons}\n"
            profit = total_win - cost
            if profit > 0: res += f"🎉 KẾT QUẢ: LÃI {format_coin(profit)}! {random.choice(WIN_MESSAGES)}"
            elif profit == 0: res += f"🤝 KẾT QUẢ: HÒA VỐN."
            else: res += f"💸 KẾT QUẢ: LỖ {format_coin(abs(profit))}! {random.choice(LOSE_MESSAGES)}"
            return res
        except: return "❌ Lỗi định dạng số."

    if msg in ["/tien", "/coin", "/xu"]:
        balance = coin_data.get(user_name, 0)
        credit = credit_data.get(user_name, 0)
        loan_limit = 2000 + (credit * 200)
        
        system_debt = 0
        if user_name in loan_data:
            system_debt = loan_data[user_name]['remaining']
        p2p_data_user = p2p_data.get(user_name, {})
        
        # --- ĐỌC SỐ LIỆU THU/CHI/LỊCH SỬ TỪ FILE ---
        wallet_stats = load_json_data("wallet_data.json", {})
        
        # Lỡ user vừa vào nhóm chưa tới 1 tiếng (chưa được chốt sổ lần nào) thì tạo data mặc định
        if user_name not in wallet_stats:
            wallet_stats[user_name] = {"income": 0, "expense": 0, "history": [balance, balance, balance]}
            
        u_stats = wallet_stats[user_name]
        income = u_stats["income"]
        expense = u_stats["expense"]
        
        # Biểu đồ lấy 2 mốc quá khứ (-2h, -1h) và mốc của NGAY HIỆN TẠI
        hist = u_stats["history"]
        history_data = [hist[-2], hist[-1], balance] if len(hist) >= 2 else [balance, balance, balance]
        
        avatar_url = user_avatars.get(user_name, "")
        img_path = tao_anh_vi(user_name, balance, income, expense, loan_limit, system_debt, p2p_data_user, history_data, avatar_url)
        
        return {"type": "image", "path": img_path, "caption": "💳 Thẻ tài khoản 💳"}

    if msg in ["/vibot", "/vitien", "/tiencuatoi"]:
        bot_balance = coin_data.get(BOT_NAME, BOT_DEFAULT_BALANCE)
        total_outstanding = sum(d.get("remaining", 0) for d in loan_data.values())
        active_borrowers = len(loan_data)
        res  = f"🏦 VÍ XU CỦA TẺN 🏦\n\n"
        res += f"💰 Số dư hiện tại: {format_coin(bot_balance)}\n"
        res += f"📤 Đang cho vay: {format_coin(total_outstanding)} ({active_borrowers} người)\n"
        res += f"🏧 Hạn mức vay 1 người: {format_coin(2000 + (credit_data.get(user_name, 0) * 200))} (tùy uy tín)\n"
        res += f"\n💡 Gõ /vay [số_xu] để mượn tiền từ ví Tẻn!"
        return res

    if msg.startswith("/chanle ") or msg.startswith("/cl "):
        parts = message_text.split()
        if len(parts) != 3: return "❌ Cú pháp: /cl [c/l] [số_tiền]"
        choice_type = 'chẵn' if parts[1] in ['chẵn', 'chan', 'c'] else ('lẻ' if parts[1] in ['lẻ', 'le', 'l'] else None)
        if not choice_type: return "❌ Chọn sai cửa!"
        try:
            bet_amt = int(parts[2])
            if bet_amt < 5: return "❌ Cược tối thiểu 5!"
            if coin_data.get(user_name, 0) < bet_amt: return f"❌ {user_name} không đủ tiền!"
            p_msg = check_and_apply_penalty(user_name, "Chẵn Lẻ", bet_amt, coin_data, player_streaks); 
            if p_msg: return p_msg
            
            pf = get_profile(user_name, profile_data)
            pf["stress"] = max(0, pf.get("stress", 0) - 5)
            save_json_data(PROFILE_FILE, profile_data)
            
            coin_data[user_name] -= bet_amt; roll = random.randint(1, 100)
            st_msg = "\n💆 (Giảm 5 Stress)"
            
            if roll in [13, 49]:
                save_json_data(COIN_FILE, coin_data)
                return f"🎲 Quay ra: 【 {roll} 】\n💀 Dính số tử! Nhà cái húp trọn! {random.choice(LOSE_MESSAGES)}{st_msg}"
            actual_type = 'chẵn' if roll % 2 == 0 else 'lẻ'
            if choice_type == actual_type:
                coin_data[user_name] += bet_amt * 2; save_json_data(COIN_FILE, coin_data)
                return f"🎲 Quay ra: 【 {roll} 】 ({actual_type.upper()})\n🎉 {user_name} HÚP {format_coin(bet_amt)}! {random.choice(WIN_MESSAGES)}{st_msg}"
            save_json_data(COIN_FILE, coin_data)
            return f"🎲 Quay ra: 【 {roll} 】 ({actual_type.upper()})\n💥 Gãy cầu! {user_name} bay màu {format_coin(bet_amt)}! {random.choice(LOSE_MESSAGES)}{st_msg}"
        except: return "Lỗi số tiền."

    if msg.startswith("/baucua ") or msg.startswith("/bc "):
        parts = message_text.split()
        if len(parts) < 3 or len(parts) > 5: 
            return "❌ Cú pháp: /baucua [ô_1] [ô_2] [ô_3] [số_xu]\n👉 Đặt tối đa 3 ô. VD: /bc cá nai tôm 500"
            
        try:
            bet_amt = int(parts[-1])
            if bet_amt < 5: return "❌ Tiền cược tối thiểu là 5 xu/ô!"
        except: return "❌ Số tiền cược không hợp lệ."

        raw_choices = [p.lower() for p in parts[1:-1]]
        valid_choices = []
        for c in raw_choices:
            if c in BAUCUA_FACES: valid_choices.append(c)
            else: return f"❌ '{c}' không tồn tại! Chỉ được chọn: bầu, cua, tôm, cá, gà, nai."
            
        valid_choices = list(set(valid_choices))
        
        if len(valid_choices) > 3:
            return "❌ Tham quá! Nhà cái chỉ cho đặt tối đa 3 ô cùng lúc thôi!"

        total_bet = bet_amt * len(valid_choices)
        
        if coin_data.get(user_name, 0) < total_bet: 
            return f"❌ Nghèo! Tính rải thảm à? Cược {len(valid_choices)} ô cần {format_coin(total_bet)}, nhưng ví chỉ có {format_coin(coin_data.get(user_name, 0))}."
            
        p_msg = check_and_apply_penalty(user_name, "Bầu Cua", total_bet, coin_data, player_streaks)
        if p_msg: return p_msg
        
        pf = get_profile(user_name, profile_data)
        pf["stress"] = max(0, pf.get("stress", 0) - 5)
        save_json_data(PROFILE_FILE, profile_data)
        
        coin_data[user_name] -= total_bet
        
        res_keys = [random.choice(list(BAUCUA_FACES.keys())) for _ in range(3)]
        
        total_won = 0
        for c in valid_choices:
            matches = res_keys.count(c)
            if matches > 0:
                total_won += bet_amt + (bet_amt * matches)
                
        coin_data[user_name] += total_won
        save_json_data(COIN_FILE, coin_data)
        
        net_profit = total_won - total_bet
        st_msg = "\n💆 (Stress -5)"
        choices_str = ", ".join([BAUCUA_FACES[c] for c in valid_choices])
        
        # FIX LỖI Ở ĐÂY: Gán giá trị mặc định cho biến img_result_msg
        img_result_msg = ""
        
        if net_profit > 0:
            img_result_msg = f"THẮNG! LÃI +{net_profit:,} XU".replace(',', '.')
            caption = f"💆 Khét lẹt! Ô cược VIP [{choices_str}] húp trọn ván bài! {user_name} rinh ngay {format_coin(net_profit)}! 🌟 {random.choice(WIN_MESSAGES)}"
        elif net_profit == 0:
            img_result_msg = "HUỀ VỐN!"
            caption = f"💆 Cược trải thảm an toàn, sếp Huề Vốn! {user_name} cược [{choices_str}] chơi tiếp đi sếp!{st_msg}"
        else:
            img_result_msg = f"THUA! LỖ -{abs(net_profit):,} XU".replace(',', '.')
            caption = f"💥 Đen! Ô cược xui xẻo [{choices_str}] bị cái nuốt gọn {format_coin(abs(net_profit))}! {user_name} thử vận may ván khác! {random.choice(LOSE_MESSAGES)}{st_msg}"

        avatar_url = user_avatars.get(user_name, "")
        img_path = tao_anh_baucua(user_name, valid_choices, bet_amt, res_keys, net_profit, img_result_msg, avatar_url)
        
        return {"type": "image", "path": img_path, "caption": caption}

    if msg.startswith("/baicao "):
        parts = message_text.split()
        if len(parts) != 2: return "❌ Cú pháp: /baicao [xu]"
        try:
            bet_amt = int(parts[1])
            if bet_amt < 5 or coin_data.get(user_name, 0) < bet_amt: return f"❌ {user_name} lỗi tiền cược!"
            p_msg = check_and_apply_penalty(user_name, "Bài Cào", bet_amt, coin_data, player_streaks)
            if p_msg: return p_msg
            
            pf = get_profile(user_name, profile_data)
            pf["stress"] = max(0, pf.get("stress", 0) - 5)
            save_json_data(PROFILE_FILE, profile_data)
            
            coin_data[user_name] -= bet_amt; deck = create_deck(); random.shuffle(deck)
            p_hand = [deck.pop(), deck.pop(), deck.pop()]; b_hand = [deck.pop(), deck.pop(), deck.pop()]
            p_sc = calculate_baicao_score(p_hand); b_sc = calculate_baicao_score(b_hand)
            if b_sc <= 4 and b_sc != 99:
                bh2 = [deck.pop(), deck.pop(), deck.pop()]; bsc2 = calculate_baicao_score(bh2)
                if bsc2 > b_sc: b_hand = bh2; b_sc = bsc2
            res = f"♠️ Bài {user_name}: [{' | '.join(p_hand)}] ({format_baicao_score(p_sc)})\n♥️ Bài Tẻn: [{' | '.join(b_hand)}] ({format_baicao_score(b_sc)})\n💆 Stress giảm 5 điểm\n"
            if p_sc > b_sc: 
                coin_data[user_name] += bet_amt * 2; res += f"🎉 {user_name} THẮNG! {random.choice(WIN_MESSAGES)}"
            elif p_sc == b_sc: 
                res += f"🤝 HÒA LÀ CÁI ĂN. {user_name} THUA! {random.choice(LOSE_MESSAGES)}"
            else: 
                res += f"💥 {user_name} THUA CÁI! {random.choice(LOSE_MESSAGES)}"
            save_json_data(COIN_FILE, coin_data); return res
        except: return "Lỗi số."
        
    # ==================== GAME CARO ====================
    if msg.startswith("//caro "):
        parts = message_text.split()
        if len(parts) < 2: return "❌ Cú pháp: /caro [xu] (Đấu Bot) hoặc /caro @Tên [xu] (Thách đấu)"
        
        # Kiểm tra xem user có đang kẹt game caro nào không
        for g_id, g in caro_games.items():
            if g["p1"] == user_name or g["p2"] == user_name:
                return "❌ Bạn đang trong một trận Caro rồi! Đánh xong đi đã."

        # THÁCH ĐẤU NGƯỜI CHƠI (PvP)
        if len(parts) >= 3 and mentioned_names:
            target_name = mentioned_names[0]
            target_name = find_exact_name(target_name, coin_data)
            try: bet_amt = int(parts[-1])
            except: return "❌ Số xu không hợp lệ!"
            
            if bet_amt < 10: return "❌ Cược Caro tối thiểu 10 xu!"
            if target_name.lower() == user_name.lower(): return "❌ Tự kỷ à? Đấu với chính mình thì cược với Bot đi!"
            
            for g_id, g in caro_games.items():
                if g["p1"] == target_name or g["p2"] == target_name:
                    return f"❌ {target_name} đang đánh Caro với người khác rồi!"
                    
            balance = coin_data.get(user_name, 0)
            if balance < bet_amt: return f"❌ Trong ví chỉ có {format_coin(balance)}, không đủ {format_coin(bet_amt)} để thách đấu!"
            
            pending_caro[target_name] = {"challenger": user_name, "bet": bet_amt, "time": time.time()}
            return f"⚔️ THÁCH ĐẤU CARO! ⚔️\n{user_name} đã thách đấu {target_name} với mức cược {format_coin(bet_amt)}.\n👉 Hỡi {target_name}, hãy gõ '/ycaro' để chấp nhận hoặc '/ncaro' để từ chối (Thời hạn 60s)!"

        # ĐẤU VỚI BOT (PvE)
        else:
            try: bet_amt = int(parts[1])
            except: return "❌ Số xu không hợp lệ!"
            
            if bet_amt < 10: return "❌ Cược tối thiểu 10 xu!"
            balance = coin_data.get(user_name, 0)
            if balance < bet_amt: return f"❌ Ví bạn không đủ {format_coin(bet_amt)}!"
            
            coin_data[user_name] -= bet_amt
            save_json_data(COIN_FILE, coin_data)
            
            game_id = f"caro_{user_name}"
            caro_games[game_id] = {
                "p1": user_name, "p2": "Tẻn", "bet": bet_amt, "type": "PvE",
                "board": [[' '] * 6 for _ in range(6)],
                "turn": "X", "last_time": time.time()
            }
            
            img_path = tao_anh_caro(user_name, "Tẻn", caro_games[game_id]["board"], bet_amt, f"Đến lượt {user_name} (X)", "X")
            return {"type": "image", "path": img_path, "caption": f"🏁 Trận đấu bắt đầu! {user_name} đi trước (X).\n👉 Gõ lệnh /c[Dọc][Ngang] để đánh. VD: /cA2 hoặc /cB3"}

    if msg == "/ycaro":
        if user_name not in pending_caro: return "❌ Bạn có lời thách đấu Caro nào đâu?"
        req = pending_caro[user_name]
        challenger = req["challenger"]
        bet = req["bet"]
        
        if time.time() - req["time"] > 60:
            del pending_caro[user_name]
            return "❌ Lời thách đấu đã quá hạn 60s!"
            
        bal1 = coin_data.get(challenger, 0)
        bal2 = coin_data.get(user_name, 0)
        
        if bal1 < bet:
            del pending_caro[user_name]
            return f"❌ {challenger} gáy to nhưng ví không đủ {format_coin(bet)}. Kèo hủy!"
        if bal2 < bet:
            del pending_caro[user_name]
            return f"❌ {user_name} không đủ tiền nhận kèo ({format_coin(bet)}). Kèo hủy!"
            
        coin_data[challenger] -= bet
        coin_data[user_name] -= bet
        save_json_data(COIN_FILE, coin_data)
        
        game_id = f"caro_{challenger}_{user_name}"
        caro_games[game_id] = {
            "p1": challenger, "p2": user_name, "bet": bet, "type": "PvP",
            "board": [[' '] * 6 for _ in range(6)], # ĐÃ SỬA THÀNH 6x6
            "turn": "X", "last_time": time.time()
        }
        del pending_caro[user_name]
        
        img_path = tao_anh_caro(challenger, user_name, caro_games[game_id]["board"], bet, f"Đến lượt {challenger} (X)", "X")
        return {"type": "image", "path": img_path, "caption": f"🏁 Võ đài sinh tử bắt đầu!\n{challenger} là X (Đi trước), {user_name} là O.\n👉 Gõ lệnh /c[Dọc][Ngang] để đánh. VD: /cA2"}

    if msg == "/ncaro":
        if user_name in pending_caro:
            challenger = pending_caro[user_name]["challenger"]
            del pending_caro[user_name]
            return f"💨 {user_name} đã từ chối lời thách đấu của {challenger}!"

    # LỆNH ĐÁNH CARO MỚI (/cA1, /cB2, /cF6...)
    if msg.startswith("/c"):
        clean_msg = msg.replace(" ", "").upper() 
        # Bắt đúng 100%: Dài 4 ký tự, bắt đầu bằng /C, ký tự 3 là A-F, ký tự 4 là 1-6
        if len(clean_msg) == 4 and clean_msg.startswith("/C") and clean_msg[2] in "ABCDEF" and clean_msg[3] in "123456":
            r_str = clean_msg[2]
            c_str = clean_msg[3]
            
            row_map = {'A': 0, 'B': 1, 'C': 2, 'D': 3, 'E': 4, 'F': 5}
            col_map = {'1': 0, '2': 1, '3': 2, '4': 3, '5': 4, '6': 5}
            
            if r_str in row_map and c_str in col_map:
                r = row_map[r_str]
                c = col_map[c_str]
                
                # Tìm trận Caro của user
                current_game_id = None
                for g_id, g in caro_games.items():
                    if g["p1"] == user_name or g["p2"] == user_name:
                        current_game_id = g_id
                        break
                        
                if not current_game_id: return None
                
                game = caro_games[current_game_id]
                p1, p2, bet = game["p1"], game["p2"], game["bet"]
                board = game["board"]
                
                # Kiểm tra lượt
                current_turn_player = p1 if game["turn"] == 'X' else p2
                current_piece = game["turn"]
                
                if user_name != current_turn_player:
                    return f"❌ Ê ê! Chưa đến lượt của {user_name} đâu nha!"
                    
                if board[r][c] != ' ':
                    return "❌ Ô này có người đánh rồi cha nội! Chọn ô khác đi."
                    
                # Cập nhật bàn cờ
                board[r][c] = current_piece
                game["last_time"] = time.time()
                
                # Kiểm tra Thắng/Hòa cho Người chơi
                winner = check_winner_caro(board)
                if winner:
                    win_money = bet * 2
                    coin_data[user_name] += win_money
                    save_json_data(COIN_FILE, coin_data)
                    img_path = tao_anh_caro(p1, p2, board, bet, f"🎉 {user_name} ĐÃ CHIẾN THẮNG (+{format_coin(bet)})!", "")
                    del caro_games[current_game_id]
                    return {"type": "image", "path": img_path, "caption": f"🏆 CHÚC MỪNG {user_name} ĐÃ CHIẾN THẮNG!\nHúp trọn {format_coin(win_money)} xu!"}
                    
                if is_board_full_caro(board):
                    coin_data[p1] += bet
                    if game["type"] == "PvP": coin_data[p2] += bet
                    save_json_data(COIN_FILE, coin_data)
                    img_path = tao_anh_caro(p1, p2, board, bet, "🤝 HÒA NHAU! TRẢ LẠI TIỀN!", "")
                    del caro_games[current_game_id]
                    return {"type": "image", "path": img_path, "caption": "🤝 Bàn cờ đã kín! Cả 2 hòa nhau và được trả lại tiền cược."}

                # Đổi lượt
                if game["type"] == "PvP":
                    game["turn"] = 'O' if current_piece == 'X' else 'X'
                    next_player = p2 if game["turn"] == 'O' else p1
                    img_path = tao_anh_caro(p1, p2, board, bet, f"Đến lượt {next_player} ({game['turn']})", game["turn"])
                    return {"type": "image", "path": img_path, "caption": f"✅ {user_name} đã đánh {r_str}{c_str}.\n👉 Tới lượt {next_player} ({game['turn']})!"}
                
                # NẾU PvE (Tới lượt BOT đánh)
                if game["type"] == "PvE":
                    bot_r, bot_c = bot_move_caro(board, 'O', 'X')
                    if bot_r is not None:
                        board[bot_r][bot_c] = 'O'
                        
                        bot_winner = check_winner_caro(board)
                        if bot_winner:
                            img_path = tao_anh_caro(p1, p2, board, bet, f"💀 MÁY THẮNG! Bạn mất {format_coin(bet)}", "")
                            del caro_games[current_game_id]
                            return {"type": "image", "path": img_path, "caption": f"🤖 Tẻn đã đi [{list(row_map.keys())[bot_r]}{list(col_map.keys())[bot_c]}].\n💀 BẠN ĐÃ THUA MÁY! Nộp mạng {format_coin(bet)} xu đây!"}
                            
                        if is_board_full_caro(board):
                            coin_data[p1] += bet
                            save_json_data(COIN_FILE, coin_data)
                            img_path = tao_anh_caro(p1, p2, board, bet, "🤝 HÒA NHAU! TRẢ LẠI TIỀN!", "")
                            del caro_games[current_game_id]
                            return {"type": "image", "path": img_path, "caption": "🤖 Tẻn đã đi rớt nước mắt. HÒA NHAU!"}
                            
                    game["turn"] = 'X'
                    game["last_time"] = time.time()
                    img_path = tao_anh_caro(p1, p2, board, bet, f"Đến lượt {p1} (X)", "X")
                    return {"type": "image", "path": img_path, "caption": f"🤖 Tẻn vừa đánh [{list(row_map.keys())[bot_r]}{list(col_map.keys())[bot_c]}].\n👉 Tới lượt {p1} (X)!"}

    if msg.startswith("/xidach "):
        if user_name in xidach_games: return f"❌ {user_name} đang chơi Xì Dách dở rồi! Gõ '/rut' / '/dung'."
        parts = message_text.split()
        if len(parts) != 2: return "❌ Cú pháp: /xidach [xu]"
        try:
            bet_amt = int(parts[1])
            if bet_amt < 5 or coin_data.get(user_name, 0) < bet_amt: return f"❌ {user_name} không đủ tiền cược."
            p_msg = check_and_apply_penalty(user_name, "Xì Dách", bet_amt, coin_data, player_streaks)
            if p_msg: return p_msg
            
            pf = get_profile(user_name, profile_data)
            pf["stress"] = max(0, pf.get("stress", 0) - 5)
            save_json_data(PROFILE_FILE, profile_data)
            
            coin_data[user_name] -= bet_amt; save_json_data(COIN_FILE, coin_data)
            deck = create_deck(); random.shuffle(deck)
            
            # --- CƠ CHẾ BỊP 1: CHIA BÀI ---
            bip_chance = 0
            if global_xd_mode == 2 and bet_amt > 5000000: bip_chance = 60
            elif global_xd_mode == 3: bip_chance = 80
            
            if bip_chance > 0 and random.randint(1, 100) <= bip_chance and 'A♠' in deck and 'K♠' in deck:
                b_hand = ['A♠', 'K♠']
                deck.remove('A♠'); deck.remove('K♠')
                p_hand = [deck.pop(), deck.pop()]
            else:
                p_hand = [deck.pop(), deck.pop()]; b_hand = [deck.pop(), deck.pop()]
            # ------------------------------
            
            ps = check_special_hand(p_hand); bs = check_special_hand(b_hand)
            
            p_score_val = calculate_score(p_hand); b_score_val = calculate_score(b_hand)
            p_status = ps if ps != "Thường" else f"{p_score_val} diem"
            b_status = bs if bs != "Thường" else f"{b_score_val} diem"
            
            is_game_over = False
            img_result_msg = ">> Go '/rut' de boc them hoac '/dung' de xet bai."
            caption = "💆 Stress giảm 5."

            if ps != "Thường" or bs != "Thường":
                is_game_over = True
                if ps == bs: 
                    coin_data[user_name] += bet_amt
                    img_result_msg = "HOA! TRA LAI TIEN!"
                    caption = "🤝 CẢ 2 HÒA NHAU! TRẢ LẠI TIỀN!"
                elif ps == "Xì Bàng" or (ps == "Xì Dách" and bs == "Thường"): 
                    coin_data[user_name] += bet_amt*2
                    img_result_msg = f"THANG TRANG! +{format_coin(bet_amt)}"
                    caption = f"🎉 THẮNG TRẮNG! +{format_coin(bet_amt)}! {random.choice(WIN_MESSAGES)}"
                else: 
                    img_result_msg = "NHA CAI THANG TRANG!"
                    caption = f"💥 NHÀ CÁI THẮNG TRẮNG! BẠN THUA! {random.choice(LOSE_MESSAGES)}"
                save_json_data(COIN_FILE, coin_data)
            else:
                xidach_games[user_name] = {"bet": bet_amt, "player_hand": p_hand, "bot_hand": b_hand, "deck": deck}

            avatar_url = user_avatars.get(user_name, "")
            img_path = tao_anh_xidach(user_name, p_hand, b_hand, p_score_val, b_score_val, p_status, b_status, is_game_over, img_result_msg, avatar_url)
            return {"type": "image", "path": img_path, "caption": caption}
        except: return "Lỗi số."

    if msg in ["/rut", "/rút"]:
        if user_name not in xidach_games: return f"❌ {user_name} có ván Xì Dách nào đâu mà đòi rút?"
        game = xidach_games[user_name]
        
        p_sc = calculate_score(game["player_hand"])
        if p_sc > 21:
            return f"💥 Á đù! Bác đã quắc rồi, Tẻn mù không thấy đâu, gõ '/dung' để lật bài đi! 😂"
            
        # --- CƠ CHẾ BỊP 2: ÉP BỐC LÁ TÂY ---
        bip_chance = 0
        if global_xd_mode == 2 and game["bet"] > 5000000 and p_sc >= 12: bip_chance = 80
        elif global_xd_mode == 3 and p_sc >= 12: bip_chance = 90
        
        if bip_chance > 0 and random.randint(1, 100) <= bip_chance:
            # Nhét lá 10, J, Q, K vào mồm người chơi để ép Quắc
            big_cards = [c for c in game["deck"] if c[:-1] in ['10', 'J', 'Q', 'K']]
            if big_cards:
                rigged_card = big_cards[0]
                game["deck"].remove(rigged_card)
                game["player_hand"].append(rigged_card)
            else:
                game["player_hand"].append(game["deck"].pop())
        else:
            game["player_hand"].append(game["deck"].pop())
        # ----------------------------------
        
        p_sc = calculate_score(game["player_hand"])
        p_status = f"{p_sc} diem"
        
        is_game_over = False
        img_result_msg = ">> Go '/rut' de boc them hoac '/dung' de xet bai."
        caption = ""

        if p_sc > 21: 
            img_result_msg = "QUAC ROI! Go '/dung' de mo bai Nha cai."
            caption = "💥 TOANG RỒI! BẠN ĐÃ QUẮC! Gõ '/dung' để mở bài Nhà cái."
        elif len(game["player_hand"]) == 5 and p_sc <= 21:
            is_game_over = True
            coin_data[user_name] = coin_data.get(user_name, 0) + (game["bet"] * 2)
            save_json_data(COIN_FILE, coin_data)
            img_result_msg = f"NGU LINH! THANG +{format_coin(game['bet'])}"
            caption = f"🎉 NGŨ LINH! MẠNG LỚN ĐẤY! BẠN ĐÃ ĐẠT NGŨ LINH VÀ THẮNG TRẮNG {format_coin(game['bet'])}!"
            b_sc = calculate_score(game["bot_hand"])
            b_status = f"{b_sc} diem"
            del xidach_games[user_name]
            
        avatar_url = user_avatars.get(user_name, "")
        b_sc_temp = calculate_score(game["bot_hand"])
        img_path = tao_anh_xidach(user_name, game["player_hand"], game["bot_hand"], p_sc, b_sc_temp, p_status, f"{b_sc_temp} diem", is_game_over, img_result_msg, avatar_url)
        return {"type": "image", "path": img_path, "caption": caption}

    if msg in ["/dung", "/dừng"]:
        if user_name not in xidach_games: return f"❌ {user_name} có ván Xì Dách nào đâu mà đòi dừng?"
        game = xidach_games[user_name]; bet = game["bet"]; p_sc = calculate_score(game["player_hand"]); b_sc = calculate_score(game["bot_hand"])
        
        # --- CƠ CHẾ BỊP 3: NHÀ CÁI BỐC BÀI THIÊN NHÃN ---
        use_thien_nhan = False
        if global_xd_mode == 2 and bet > 5000000 and p_sc <= 21: use_thien_nhan = True
        elif global_xd_mode == 3 and p_sc <= 21: use_thien_nhan = True
        
        if use_thien_nhan:
            while b_sc <= p_sc and b_sc < 21 and len(game["bot_hand"]) < 5:
                needed = 21 - b_sc
                safe_cards = [c for c in game["deck"] if get_card_value(c) <= needed]
                perfect_cards = [c for c in safe_cards if b_sc + get_card_value(c) > p_sc]
                
                if perfect_cards: chosen = perfect_cards[0] # Lụm lá giúp thắng luôn
                elif safe_cards: chosen = safe_cards[0]     # Không có thì lụm lá an toàn
                else: break                                 # Hết đường cứu
                
                game["deck"].remove(chosen)
                game["bot_hand"].append(chosen)
                b_sc = calculate_score(game["bot_hand"])
        else:
            # LOGIC XÌ DÁCH TRUNG THỰC (Cho bọn cược nhỏ)
            while b_sc < 15 and len(game["bot_hand"]) < 5:
                game["bot_hand"].append(game["deck"].pop())
                b_sc = calculate_score(game["bot_hand"])
                
            while 15 <= b_sc <= 20 and len(game["bot_hand"]) < 5:
                probs = {15: 80, 16: 60, 17: 40, 18: 20, 19: 5, 20: 1}
                if random.randint(1, 100) <= probs.get(b_sc, 0):
                    game["bot_hand"].append(game["deck"].pop())
                    b_sc = calculate_score(game["bot_hand"])
                else:
                    break
        # ------------------------------------------------
                    
        p_status = f"Quac ({p_sc})" if p_sc > 21 else f"{p_sc} diem"
        if len(game["bot_hand"]) == 5 and b_sc <= 21: b_status = "Ngu Linh"
        else: b_status = f"Quac ({b_sc})" if b_sc > 21 else f"{b_sc} diem"
        
        del xidach_games[user_name]
        
        if len(game["bot_hand"]) == 5 and b_sc <= 21:
            img_result_msg = "NHA CAI NGU LINH! BAN THUA SACH!"
            caption = "💥 TẺN RÚT ĐƯỢC NGŨ LINH! NHÀ CÁI ĐÃ NUỐT GỌN TIỀN CỦA BẠN!"
        elif p_sc > 21:
            if b_sc > 21:
                coin_data[user_name] += bet
                img_result_msg = "CA 2 DEU QUAC! HOA TIEN!"
                caption = "🤝 CẢ HAI ĐỀU QUẮC! HÙỀ TIỀN!"
            else:
                img_result_msg = "BAN QUAC VA DA THUA!"
                caption = f"💥 BẠN QUẮC VÀ ĐÃ THUA! Tẻn lụm bạc! {random.choice(LOSE_MESSAGES)}"
        elif b_sc > 21 or p_sc > b_sc: 
            coin_data[user_name] += bet*2
            img_result_msg = f"BAN THANG +{format_coin(bet)}"
            caption = f"🎉 BẠN THẮNG! {random.choice(WIN_MESSAGES)}"
        elif p_sc == b_sc: 
            coin_data[user_name] += bet
            img_result_msg = "HOA DIEM! TRA LAI TIEN"
            caption = "🤝 HÒA ĐIỂM."
        else: 
            img_result_msg = "NHA CAI CAO DIEM HON! BAN THUA!"
            caption = f"💥 NHÀ CÁI THẮNG! {random.choice(LOSE_MESSAGES)}"
            
        save_json_data(COIN_FILE, coin_data)
        avatar_url = user_avatars.get(user_name, "")
        img_path = tao_anh_xidach(user_name, game["player_hand"], game["bot_hand"], p_sc, b_sc, p_status, b_status, True, img_result_msg, avatar_url)
        return {"type": "image", "path": img_path, "caption": caption}

    if msg in ["/huyxd"]:
        if user_name in xidach_games:
            coin_data[user_name] = coin_data.get(user_name, 0) + xidach_games[user_name]["bet"]
            save_json_data(COIN_FILE, coin_data)
            del xidach_games[user_name]
            return f"✅ Đã hủy ván Xì Dách bị kẹt của {user_name} và hoàn lại tiền cược."
        return f"❌ {user_name} không có ván Xì Dách nào đang kẹt."
        
    if msg in ["/tarot", "/boi", "/rutbai"]:
        balance = coin_data.get(user_name, 0)
        if balance < 50:
            return f"❌ Nghèo! {user_name} cần 50 xu để đặt quẻ Tarot nhưng chỉ có {format_coin(balance)}."

        # Trừ xu và khởi tạo session bước 1
        coin_data[user_name] -= 50
        save_json_data(COIN_FILE, coin_data)

        pending_tarot_sessions[user_name] = {"step": "waiting_question"}

        # Trả về list hỗn hợp: ảnh bàn tarot + 2 tin nhắn
        return [
            {"type": "image", "path": TAROT_TABLE_IMG, "caption": "🕯️ Đang thanh tẩy và chuẩn bị..."},
            f"✨ Không gian linh thiêng đã sẵn sàng, {user_name}!\n💸 Đã trừ 50 xu.",
            "🔮 Bạn đang băn khoăn điều gì? Hãy trình bày chủ đề hoặc câu hỏi của bạn cho Tẻn nhé!\n(Gõ câu hỏi của bạn vào đây ↓)"
        ]

    if msg in ["/tin", "/news"]:
        news_msg = fetch_vnexpress_top_story()
        if news_msg: return news_msg
        return "Báo hôm nay ế, chưa có tin nóng nào ông ơi!"

    if msg.startswith("/pick"):
        options = message_text.split()[1:]
        if len(options) < 2: return "Nhập ít nhất 2 cái để tui chọn chứ!"
        return f"🎲 Chốt đơn: {random.choice(options).upper()} nha!"

    if msg == "/roll":
        score = random.randint(1, 100)
        if score > 80: return f"🎲 {user_name} lắc được {score} điểm! Nhân phẩm chói lóa!"
        elif score < 20: return f"🎲 {user_name} lắc được {score} điểm... Xui vãi chưởng!"
        return f"🎲 {user_name} lắc được {score} điểm. Bình thường!"

    if msg == "/slot":
        cost = 500
        balance = coin_data.get(user_name, 0)
        if balance < cost: return f"❌ Nghèo! Cần {format_coin(cost)} để gạt cần Slot Machine."
        
        # Deduct
        coin_data[user_name] -= cost
        save_json_data(COIN_FILE, coin_data)
        
        symbols = ['🍒', '🍋', '🔔', '💎', '7️⃣', '🍉', '⭐']
        results = [random.choice(symbols) for _ in range(5)]
        
        messages = [f"🎰 {user_name} gạt cần Slot Machine (Tốn {format_coin(cost)})..."]
        
        for i in range(1, 6):
            slots = results[:i] + ['❓'] * (5 - i)
            messages.append(f"【 {' | '.join(slots)} 】")
            
        max_count = max(results.count(s) for s in set(results))
        
        if max_count == 5:
            prize = 300000
            coin_data[user_name] += prize
            save_json_data(COIN_FILE, coin_data)
            messages.append(f"🎉 NỔ HŨ!!! BẠN TRÚNG MÁNH {format_coin(prize)}! Quá dữ!")
        elif max_count == 4:
            prize = 50000
            coin_data[user_name] += prize
            save_json_data(COIN_FILE, coin_data)
            messages.append(f"🎊 Chúc mừng! 4 biểu tượng giống nhau! Trúng {format_coin(prize)}!")
        elif max_count == 3:
            prize = 5000
            coin_data[user_name] += prize
            save_json_data(COIN_FILE, coin_data)
            messages.append(f"🎉 Khá lắm! 3 biểu tượng giống nhau! Trúng {format_coin(prize)}!")
        else:
            messages.append(f"💥 Xịt rồi! Trắng tay {format_coin(cost)}.")
            
        return messages

    if msg == "/top":
        if not user_msg_counts: return "Chưa có ai nhắn chữ nào ráo!"
        sorted_counts = sorted(user_msg_counts.items(), key=lambda item: item[1], reverse=True)
        reply = "🏆 BẢNG XẾP HẠNG THÁNH CHAT 🏆\n"
        for i, (name, count) in enumerate(sorted_counts): reply += f"Top {i+1}. {name}: {count} tin nhắn\n"
        return reply

    return None

# ==============================================================================
# ⚙️ CÁC HÀM TƯƠNG TÁC ZALO & MAIN LOOP
# ==============================================================================

def init_browser():
    options = webdriver.ChromeOptions()
    profile_path = os.path.join(os.getcwd(), "zalo_profile")
    if not os.path.exists(profile_path): os.makedirs(profile_path)
    options.add_argument(f"user-data-dir={profile_path}")
    
    # Cấu hình tối ưu cho VPS 2 core / 2GB RAM
    options.add_argument("--headless=new") 
    options.add_argument("--window-size=1920,1080")
    options.add_argument("--no-sandbox") 
    options.add_argument("--disable-dev-shm-usage") 
    options.add_argument("--disable-gpu") 
    options.add_argument("--disable-software-rasterizer")
    options.add_argument("--disable-extensions")
    options.add_argument("--disable-background-networking")     # Tắt kết nối nền của Chrome
    options.add_argument("--disable-background-timer-throttling")
    options.add_argument("--disable-renderer-backgrounding")    # Không giảm ưu tiên tab nền
    options.add_argument("--disable-backgrounding-occluded-windows")
    options.add_argument("--renderer-process-limit=1")          # Chỉ 1 renderer process
    options.add_argument("--js-flags=--max-old-space-size=256") # Giới hạn V8 heap 256MB
    options.add_argument("--disk-cache-size=1")                 # Tắt disk cache (dùng RAM cache thay thế)
    options.add_argument("--media-cache-size=1")                # Tắt media cache
    options.add_argument("--disable-logging")                   # Tắt ghi log ẩn của Chrome
    options.add_argument("--log-level=3")                       # Chỉ log lỗi nghiêm trọng
    
    try:
        srv = Service(ChromeDriverManager().install())
    except Exception as e:
        print(f"Lưu ý: Mạng chậm không thể tải WebDriver. Tự động chuyển fallback. ({e})")
        srv = Service()
        
    driver = webdriver.Chrome(service=srv, options=options)
    driver.get("https://chat.zalo.me")
    return driver


def login_google_once():
    """
    ⚠️  CHẠY 1 LẦN DUY NHẤT để login Google vào profile zalo_profile.
    Sau khi chạy xong, headless bot sẽ tự dùng session đã lưu.

    Cách chạy trên VPS (cần có màn hình / VNC / X11 forwarding):
        python3 -c "from botzalobeta import login_google_once; login_google_once()"

    Hoặc qua SSH với X11 forwarding:
        ssh -X user@your_vps
        python3 -c "from botzalobeta import login_google_once; login_google_once()"
    """
    options = webdriver.ChromeOptions()
    profile_path = os.path.join(os.getcwd(), "zalo_profile")
    if not os.path.exists(profile_path):
        os.makedirs(profile_path)
    options.add_argument(f"user-data-dir={profile_path}")
    # KHÔNG dùng --headless — cần giao diện để login thủ công
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")

    try:
        srv = Service(ChromeDriverManager().install())
    except Exception:
        srv = Service()

    drv = webdriver.Chrome(service=srv, options=options)
    drv.get("https://accounts.google.com")
    print("👉 Hãy login Google trong cửa sổ Chrome vừa mở.")
    print("   Sau khi login xong, quay lại terminal và nhấn Enter.")
    input("   [Nhấn Enter để đóng và lưu session] ")
    drv.quit()
    print("✅ Đã lưu session Google vào profile. Bot headless sẽ tự dùng từ lần sau.")


def gui_anh_zalo(driver, image_data, caption=""):
    try:
        # 🧠 BÍ THUẬT ÉP RAM: Phân biệt Base64 RAM và File Path ổ cứng
        if len(image_data) > 500:
            b64_str = image_data # Chuỗi siêu dài chắc chắn là Base64 trên RAM
        else:
            with open(image_data, "rb") as f:
                b64_str = base64.b64encode(f.read()).decode('utf-8')
        
        input_box = driver.find_element(By.ID, "richInput")
        input_box.click()
        input_box.send_keys(Keys.CONTROL, "a")
        input_box.send_keys(Keys.DELETE)
        time.sleep(0.5)
        
        # Bước 1: Mô phỏng hành động dán (Paste) ảnh trực tiếp vào khung chat Zalo
        js_paste_img = """
        const b64Str = arguments[0];
        const byteCharacters = atob(b64Str);
        const byteNumbers = new Array(byteCharacters.length);
        for (let i = 0; i < byteCharacters.length; i++) {
            byteNumbers[i] = byteCharacters.charCodeAt(i);
        }
        const byteArray = new Uint8Array(byteNumbers);
        const blob = new Blob([byteArray], {type: 'image/png'});
        const file = new File([blob], 'image.png', {type: 'image/png'});
        
        const dt = new DataTransfer();
        dt.items.add(file);
        
        const el = document.getElementById('richInput');
        const evt = new ClipboardEvent('paste', { clipboardData: dt, bubbles: true });
        el.dispatchEvent(evt);
        """
        driver.execute_script(js_paste_img, b64_str)
        time.sleep(1.5) 
        
        # Bước 2: Dán tiếp đoạn text caption vào nếu có
        if caption:
            js_paste_text = """
            const dt = new DataTransfer();
            dt.setData('text/plain', arguments[0]);
            const el = document.getElementById('richInput');
            const evt = new ClipboardEvent('paste', { clipboardData: dt, bubbles: true });
            el.dispatchEvent(evt);
            """
            driver.execute_script(js_paste_text, caption)
            time.sleep(1)
        
        # Bước 3: Ấn gửi
        # 🧠 FIX: Bấm thẳng vào cái class 'send-msg-btn' mới nhất của Zalo, nếu xịt thì bồi thêm phím Enter
        try:
            driver.find_element(By.CSS_SELECTOR, ".send-msg-btn").click()
        except:
            input_box.send_keys(Keys.ENTER)
    except Exception as e:
        print(f"❌ Lỗi gửi ảnh: {e}")
        return False


def normalize_video_url(url):
    """
    Chuẩn hóa URL Facebook/TikTok/YouTube trước khi đưa vào downloader.
    Tự động trích xuất ID số (10-20 chữ số) từ link share/watch/reel/fb.watch để tránh lỗi 'Cannot parse data' của yt-dlp.
    Ví dụ:
    - https://www.facebook.com/share/r/1498614348705271/?mibextid=xxx -> https://www.facebook.com/1498614348705271
    - https://fb.watch/1498614348705271/ -> https://www.facebook.com/1498614348705271
    """
    url_str = str(url).strip().strip("<>").strip()
    if any(domain in url_str.lower() for domain in ["facebook.com", "fb.watch", "fb.gg"]):
        match = re.search(r'(\d{10,20})', url_str)
        if match:
            return f"https://www.facebook.com/{match.group(1)}"
        try:
            r = requests.head(url_str, headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}, allow_redirects=True, timeout=5)
            final_url = r.url
            match_final = re.search(r'(\d{10,20})', final_url)
            if match_final:
                return f"https://www.facebook.com/{match_final.group(1)}"
            return final_url
        except Exception:
            pass
    return url_str


def download_video_web(target_url, output_dir):
    """
    Tải video đa nền tảng (Facebook, YouTube, TikTok, Instagram, Twitter/X...):
    1. Ưu tiên sử dụng thư viện yt-dlp trực tiếp (tốc độ cao, không phụ thuộc trình duyệt web cào).
    2. Nếu yt-dlp gặp lỗi, fallback sang Selenium cào link từ trang web hỗ trợ (fsave, xsaver, savevid, ytsave).
    """
    target_url = normalize_video_url(target_url)

    # ─── CÁCH 1: DÙNG YT-DLP TRỰC TIẾP ───────────────────────────────────────
    try:
        import yt_dlp
        unique_id = str(uuid.uuid4())[:8]
        out_template = os.path.join(output_dir, f"temp_video_{unique_id}.%(ext)s")
        ydl_opts = {
            'format': 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best',
            'outtmpl': out_template,
            'quiet': True,
            'no_warnings': True,
            'max_filesize': 100 * 1024 * 1024, # 100MB
            'user_agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36',
        }
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(target_url, download=True)
            filename = ydl.prepare_filename(info)
            if os.path.exists(filename) and os.path.getsize(filename) > 50000:
                with open(filename, "rb") as check_f:
                    header = check_f.read(500)
                if b"<!DOCTYPE" not in header and b"<html" not in header and b"<!doctype" not in header:
                    print(f"✅ [yt-dlp] Tải video thành công: {filename}")
                    return filename
    except Exception as e:
        print(f"⚠️ [yt-dlp] Lỗi tải video qua yt-dlp: {e}. Đang thử fallback qua Selenium web scraper...")

    # ─── CÁCH 2: FALLBACK CÀO LINK QUA SELENIUM ──────────────────────────────
    url_lower = target_url.lower()
    site_url = None
    if "facebook.com" in url_lower or "fb.watch" in url_lower or "fb.gg" in url_lower:
        site_url = "https://fsave.net/vi"
    elif "x.com" in url_lower or "twitter.com" in url_lower:
        site_url = "https://www.xsaver.io/x-downloader/vi/"
    elif "instagram.com" in url_lower:
        site_url = "https://savevid.to/vi"
    elif "youtube.com" in url_lower or "youtu.be" in url_lower:
        site_url = "https://ytsave.to/vi2/"

    if not site_url:
        return None

    options = webdriver.ChromeOptions()
    options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--mute-audio")
    options.add_argument("--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36")

    helper_driver = None
    try:
        try:
            service = Service(ChromeDriverManager().install())
            helper_driver = webdriver.Chrome(service=service, options=options)
        except Exception:
            helper_driver = webdriver.Chrome(options=options)

        helper_driver.set_window_size(1280, 850)
        helper_driver.execute_cdp_cmd('Page.addScriptToEvaluateOnNewDocument', {
            'source': 'Object.defineProperty(navigator, "webdriver", {get: () => undefined})'
        })
        helper_driver.get(site_url)
        time.sleep(2)

        # 1. Tìm ô nhập link
        inputs = helper_driver.find_elements(By.CSS_SELECTOR, "input#postUrl, input[name='url'], input[type='text'], input[type='url'], #k_url, #url")
        if not inputs:
            helper_driver.quit()
            return None

        input_field = inputs[0]
        input_field.clear()
        input_field.send_keys(target_url)
        time.sleep(0.5)

        # 2. Bấm nút Submit / Tải xuống
        submit_btns = helper_driver.find_elements(By.CSS_SELECTOR, "#loadVideos, button[type='submit'], input[type='submit'], #k_btn, .btn-search, button.btn")
        if submit_btns:
            submit_btns[0].click()
        else:
            input_field.send_keys(Keys.ENTER)

        # 3. Chờ kết quả tải xuất hiện
        time.sleep(6)

        # Tìm các link/nút tải file
        direct_url = None
        elements = helper_driver.find_elements(By.CSS_SELECTOR, "a[href], button[onclick]")
        for elem in elements:
            href = elem.get_attribute("href") or ""
            text = elem.text.strip().lower()
            if any(ext in href.lower() for ext in [".mp4", "download.php", "googlevideo.com", "fbcdn.net", "twimg.com", "cdninstagram.com"]):
                direct_url = href
                break
            elif ("tải" in text or "download" in text or "mp4" in text or "hd" in text) and href.startswith("http") and site_url not in href:
                direct_url = href
                break

        if not direct_url:
            render_btns = helper_driver.find_elements(By.XPATH, "//a[contains(text(), 'Tải') or contains(text(), 'Download') or contains(text(), 'Render')]")
            if render_btns:
                try:
                    helper_driver.execute_script("arguments[0].click();", render_btns[0])
                    time.sleep(3)
                    new_links = helper_driver.find_elements(By.CSS_SELECTOR, "a[href^='http']")
                    for nl in new_links:
                        nhref = nl.get_attribute("href")
                        if nhref and site_url not in nhref and any(k in nhref for k in [".mp4", "download", "video"]):
                            direct_url = nhref
                            break
                except Exception:
                    pass

        helper_driver.quit()

        if not direct_url:
            return None

        # 4. Tải file video về ổ cứng
        res = requests.get(direct_url, stream=True, headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36"
        }, timeout=40)

        if res.status_code == 200:
            unique_id = str(uuid.uuid4())[:8]
            filepath = os.path.join(output_dir, f"temp_video_{unique_id}.mp4")
            with open(filepath, "wb") as f:
                for chunk in res.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)

            # Kiểm tra tính hợp lệ của file mp4 (dung lượng > 50KB và không phải HTML lỗi)
            if os.path.exists(filepath) and os.path.getsize(filepath) > 50000:
                with open(filepath, "rb") as check_f:
                    header = check_f.read(500)
                if b"<!DOCTYPE" not in header and b"<html" not in header and b"<!doctype" not in header:
                    return filepath

            if os.path.exists(filepath):
                try:
                    os.remove(filepath)
                except Exception:
                    pass

        return None
    except Exception as e:
        print(f"⚠️ [Web Downloader] Lỗi tải video qua web: {e}")
        if helper_driver:
            try:
                helper_driver.quit()
            except Exception:
                pass
        return None


def gui_video_zalo(driver, video_path, caption=""):
    """Gửi video phát trực tiếp được trong nhóm chat Zalo qua Selenium."""
    try:
        abs_path = os.path.abspath(video_path)
        if not os.path.exists(abs_path) or os.path.getsize(abs_path) < 1000:
            print(f"❌ File video không hợp lệ: {abs_path}")
            return False

        # 🧠 BƯỚC 1: Đưa đường dẫn file video vào input[type='file'] của Zalo
        # Điều này kích hoạt Zalo Web xử lý Video chuẩn (phát được trực tiếp)
        uploaded = False
        file_inputs = driver.find_elements(By.CSS_SELECTOR, "input[type='file']")
        if file_inputs:
            for fi in reversed(file_inputs):
                try:
                    fi.send_keys(abs_path)
                    uploaded = True
                    time.sleep(2.5)
                    break
                except Exception:
                    pass

        # Fallback dán clipboard nếu không tìm thấy file input
        if not uploaded:
            with open(abs_path, "rb") as f:
                b64_str = base64.b64encode(f.read()).decode('utf-8')

            input_box = driver.find_element(By.ID, "richInput")
            input_box.click()
            input_box.send_keys(Keys.CONTROL, "a")
            input_box.send_keys(Keys.DELETE)
            time.sleep(0.5)

            js_paste_video = """
            const b64Str = arguments[0];
            const byteCharacters = atob(b64Str);
            const byteNumbers = new Array(byteCharacters.length);
            for (let i = 0; i < byteCharacters.length; i++) {
                byteNumbers[i] = byteCharacters.charCodeAt(i);
            }
            const byteArray = new Uint8Array(byteNumbers);
            const blob = new Blob([byteArray], {type: 'video/mp4'});
            const file = new File([blob], 'video.mp4', {type: 'video/mp4'});
            
            const dt = new DataTransfer();
            dt.items.add(file);
            
            const el = document.getElementById('richInput');
            const evt = new ClipboardEvent('paste', { clipboardData: dt, bubbles: true });
            el.dispatchEvent(evt);
            """
            driver.execute_script(js_paste_video, b64_str)
            time.sleep(2.0)

        # 🧠 BƯỚC 2: Nhập caption nếu có
        if caption:
            try:
                js_paste_text = """
                const dt = new DataTransfer();
                dt.setData('text/plain', arguments[0]);
                const el = document.getElementById('richInput');
                const evt = new ClipboardEvent('paste', { clipboardData: dt, bubbles: true });
                el.dispatchEvent(evt);
                """
                driver.execute_script(js_paste_text, caption)
                time.sleep(1)
            except Exception:
                pass

        # 🧠 BƯỚC 3: Bấm nút gửi
        try:
            send_btns = driver.find_elements(By.CSS_SELECTOR, ".send-msg-btn, button.btn-primary, [data-translate-inner='STR_SEND']")
            if send_btns:
                send_btns[0].click()
            else:
                input_box = driver.find_element(By.ID, "richInput")
                input_box.send_keys(Keys.ENTER)
        except Exception:
            try:
                input_box = driver.find_element(By.ID, "richInput")
                input_box.send_keys(Keys.ENTER)
            except Exception:
                pass

        time.sleep(2.0)
        return True
    except Exception as e:
        print(f"❌ Lỗi gửi video Zalo: {e}")
        return False
    except Exception as e:
        print(f"❌ Lỗi gửi video Zalo: {e}")
        return False


# ==============================================================================
# 🖼️ DECORATOR: Tự động offload mọi hàm tao_anh_* sang _pil_render_pool
# Main thread submit task → PIL render trên thread riêng → .result() lấy về
# Selenium không bị block trong khi PIL đang resize/draw ảnh nặng
# ==============================================================================
def _pil_offload(fn):
    """Decorator: chạy hàm trong _pil_render_pool, trả về kết quả đồng bộ."""
    import functools
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        future = _pil_render_pool.submit(fn, *args, **kwargs)
        return future.result()  # Chờ PIL xong rồi mới tiếp tục — nhưng GIL được nhả cho Selenium
    return wrapper

@_pil_offload
def tao_anh_profile(user_name, pf, used_management, balance, total_assets, avatar_url="", bg_id="background-df"):
    width, height = 1200, 800
    path_bg = f"/home/binh/Bản tải về/botzalo/background_profile/{bg_id}.jpg"
    
    try:
        img_bg_orig = Image.open(path_bg).convert("RGB")
        img_bg = img_bg_orig.resize((width, height), Image.LANCZOS)
    except Exception as e:
        img_bg = Image.new('RGB', (width, height), color='#2b2d31') 

    overlay = Image.new('RGBA', (width, height), (0, 0, 0, 0))
    draw_ov = ImageDraw.Draw(overlay)
    
    for y in range(height):
        ratio = y / height
        r = int(255 - ratio * 240) 
        g = int(255 - ratio * 235) 
        b = int(255 - ratio * 225) 
        a = int(40 + ratio * 180)  
        draw_ov.line([(0, y), (width, y)], fill=(r, g, b, a))

    final_img = Image.alpha_composite(img_bg.convert("RGBA"), overlay).convert("RGB")
    draw = ImageDraw.Draw(final_img)
    
    font_title = get_font(64)
    font_text = get_font(40)
    
    if avatar_url:
        avt = get_cached_avatar(avatar_url, size=(220, 220))
        if avt:
            try:
                mask_avt = Image.new('L', (220, 220), 0)
                ImageDraw.Draw(mask_avt).rounded_rectangle([0, 0, 220, 220], radius=35, fill=255)
                final_img.paste(avt, (50, 100), mask_avt)
            except Exception as e:
                print(f"⚠️ [PIL] Lỗi paste avatar profile: {e}")

    draw.text((280, 200), f"{user_name}", font=font_text, fill=(255, 255, 255), anchor="lm", stroke_width=1, stroke_fill=(255, 255, 255))
    
    def draw_bar(x, y, w, h, progress, max_val, color_rgba):
        bar_overlay = Image.new('RGBA', (w, h), (0, 0, 0, 0))
        draw_ov = ImageDraw.Draw(bar_overlay)
        draw_ov.rounded_rectangle([0, 0, w, h], radius=15, fill=(0, 0, 0, 120), outline=(255, 255, 255, 40), width=1)
        fill_w = int((progress / max_val) * w) if max_val > 0 else 0
        if fill_w > 0: draw_ov.rounded_rectangle([0, 0, fill_w, h], radius=15, fill=color_rgba)
        final_img.paste(bar_overlay, (x, y), bar_overlay)

    def paste_icon(icon_name, x, y):
        icon_path = os.path.join(r"/home/binh/Bản tải về/botzalo/icons", icon_name)
        try:
            icon_img = Image.open(icon_path).convert("RGBA")
            icon_img = icon_img.resize((48, 48), Image.LANCZOS) 
            final_img.paste(icon_img, (x, y), icon_img)
        except Exception as e:
            print(f"⚠️ [PIL] paste_icon {icon_name}: {e}")

    draw_bar(50, 360, 600, 70, pf['health'], pf['max_health'], (255, 255, 255, 110))
    paste_icon("strength.png", 80, 370)
    draw_bar(680, 360, 200, 70, 0, 100, (255, 255, 255, 110))
    draw.text((780, 395), f"{pf['health']}/{pf['max_health']}", font=font_text, fill="#ffffff", stroke_width=1, anchor="mm")

    draw_bar(50, 460, 600, 70, used_management, pf['management_limit'], (255, 255, 255, 110))
    paste_icon("management.png", 80, 470)
    draw_bar(680, 460, 200, 70, 0, 100, (255, 255, 255, 110))
    draw.text((780, 495), f"{used_management}/{pf['management_limit']}", font=font_text, fill="#ffffff", stroke_width=1, anchor="mm")

    draw_bar(50, 560, 600, 70, pf['stress'], 100, (255, 255, 255, 110))
    paste_icon("stress.png", 80, 570)
    draw_bar(680, 560, 200, 70, 0, 100, (255, 255, 255, 110))
    draw.text((780, 595), f"{pf['stress']}/100", font=font_text, fill="#ffffff", stroke_width=1, anchor="mm")

    paste_icon("iq.png", 280, 250)
    draw.text((340, 250), f"{pf['iq']:.2f}", font=font_text, fill="#ffffff", stroke_width=1)
    
    paste_icon("coin.png", 50, 650)
    draw.text((110, 650), f"{balance:,}".replace(',', '.'), font=font_text, fill="#fe7e1d", stroke_width=1)
    
    paste_icon("asset-management.png", 50, 710)
    draw.text((110, 710), f"{total_assets:,}".replace(',', '.'), font=font_text, fill="#ff4e3a", stroke_width=1)

    # 🚀 ÉP LÊN RAM
    buffered = BytesIO()
    # 💡 JPEG giảm size 60-70% so với PNG, tốc độ gửi Zalo nhanh hơn
    final_img.save(buffered, format="JPEG", quality=78)
    return base64.b64encode(buffered.getvalue()).decode('utf-8')
    
@_pil_offload
def tao_anh_taisan(user_name, balance, u_gold, gp, businesses, user_inv, avatar_url=""):
    num_biz = len(businesses)
    base_height = 550
    img_height = base_height + max(1, num_biz) * 60 + 50
    
    img = Image.new('RGB', (1280, img_height), color='#2b2d31')
    draw = ImageDraw.Draw(img)

    def paste_icon(icon_name, x, y):
        icon_path = os.path.join(r"/home/binh/Bản tải về/botzalo/icons/", icon_name)
        try:
            icon_img = Image.open(icon_path).convert("RGBA")
            icon_img = icon_img.resize((48, 48), Image.LANCZOS) 
            img.paste(icon_img, (x, y), icon_img)
        except Exception as e:
            print(f"⚠️ [PIL] paste_icon taisan {icon_name}: {e}")
    
    font_title = get_font(45)
    font_header = get_font(26)
    font_text = get_font(32)
    
    text_x = 40
    if avatar_url:
        avt = get_cached_avatar(avatar_url, size=(80, 80), circle=True)
        if avt:
            try:
                img.paste(avt, (40, 30), avt)
                text_x = 140
            except Exception as e:
                print(f"⚠️ [PIL] paste avatar taisan: {e}")
        
    draw.text((text_x, 35), f"BÁO CÁO TÀI SẢN: {user_name.upper()}", font=font_title, fill="#f1c40f")
    draw.text((text_x, 85), f"Tiền mặt khả dụng: {balance:,} xu".replace(',', '.'), font=font_text, fill="#85c1e9")
    draw.line([(40, 130), (1240, 130)], fill='#404249', width=3) 

    draw.text((40, 160), "1. KHO VÀNG SJC", font=font_text, fill="#e67e22")
    draw.rectangle([40, 210, 1240, 260], fill="#1e1e24") 
    
    cols1 = [("LOẠI VÀNG", 60), ("GIÁ THU MUA", 320), ("GIÁ BÁN RA", 600), ("SỞ HỮU", 880), ("LÃI (BÁN)", 1050)]
    for name, x in cols1: draw.text((x, 222), name, font=font_header, fill="#95a5a6")
        
    def draw_gold_row(y, name, g_type, icon_file):
        buy_p = gp.get(f"{g_type}_mua", 0)
        sell_p = gp.get(f"{g_type}_ban", 0)
        qty = u_gold.get(g_type, 0)
        profit = qty * buy_p
        paste_icon(icon_file, 60, y - 8)
        draw.text((120, y), name, font=font_text, fill="#f1c40f")
        draw.text((320, y), f"{buy_p:,}".replace(',', '.'), font=font_text, fill="#2ecc71")
        draw.text((600, y), f"{sell_p:,}".replace(',', '.'), font=font_text, fill="#e74c3c")
        draw.text((880, y), f"{qty}", font=font_text, fill="#ffffff")
        draw.text((1050, y), f"{profit:,}".replace(',', '.'), font=font_text, fill="#85c1e9" if profit > 0 else "#7f8c8d")
        draw.line([(40, y+45), (1240, y+45)], fill='#36393f', width=1)

    draw_gold_row(275, "Vàng Nhẫn", "nhan", "gold-ring.png")
    draw_gold_row(335, "Vàng Miếng", "mieng", "gold-bar.png")

    y_biz = 430
    draw.text((40, y_biz), f"2. CƠ SỞ KINH DOANH ({num_biz})", font=font_text, fill="#3498db")
    y_biz += 50
    draw.rectangle([40, y_biz, 1240, y_biz+50], fill="#1e1e24") 
    
    cols2 = [("ID", 60), ("TÊN CƠ SỞ", 130), ("NHÂN VIÊN", 460), ("MẶT BẰNG", 660), ("QUỸ / KHO", 880), ("TIÊU HAO", 1080)]
    for name, x in cols2: draw.text((x, y_biz+12), name, font=font_header, fill="#95a5a6")
    
    y_biz += 65
    if not businesses:
        draw.text((60, y_biz), "Bạn chưa sở hữu cơ sở kinh doanh nào. Gõ /kn để bắt đầu!", font=font_text, fill="#e74c3c")
    else:
        for i, b in enumerate(businesses):
            nganh = b.get("id_nganh", "")
            qm_id = int(b.get("id_quy_mo", 1))
            rent = int(b.get("von", 0) * 0.05)
            
            emp = b.get("employees", 0)
            max_emp = MAX_EMP.get(qm_id, 2)
            emp_str = f"{emp}/{max_emp}"
            
            if nganh == "nh":
                reserves = b.get('bank_reserves', 0)
                usage = int(b.get('lai', 0) * 0.05)
                stock_str = f"{reserves:,}".replace(',', '.')
                usage_str = f"-{usage:,}".replace(',', '.')
            else:
                mats = user_inv.get("materials", {}).get(nganh, 0)
                usage = MAT_USAGE.get(qm_id, 15)
                stock_str = f"{mats}/100"
                usage_str = f"-{usage} đv"

            draw.text((60, y_biz), f"[{i}]", font=font_text, fill="#bdc3c7")
            t_name = b['ten'] if len(b['ten']) < 18 else b['ten'][:15] + "..."
            draw.text((130, y_biz), t_name, font=font_text, fill="#ffffff")
            draw.text((460, y_biz), emp_str, font=font_text, fill="#f1c40f")
            draw.text((660, y_biz), f"-{rent:,}".replace(',', '.'), font=font_text, fill="#e74c3c")
            draw.text((880, y_biz), stock_str, font=font_text, fill="#2ecc71")
            draw.text((1080, y_biz), usage_str, font=font_text, fill="#f39c12")
            draw.line([(40, y_biz+45), (1240, y_biz+45)], fill='#36393f', width=1)
            y_biz += 60

    # 🚀 ÉP LÊN RAM
    buffered = BytesIO()
    # 💡 JPEG giảm size 60-70% so với PNG, tốc độ gửi Zalo nhanh hơn
    img.save(buffered, format="JPEG", quality=78)
    return base64.b64encode(buffered.getvalue()).decode('utf-8')

@_pil_offload
def tao_anh_tong_ket_nha(user_name, stats, avatar_url=""):
    num_biz = len(stats)
    img_height = 250 + max(1, num_biz) * 60 + 80
    img = Image.new('RGB', (1280, img_height), color='#2b2d31')
    draw = ImageDraw.Draw(img)
    
    font_title = get_font(36)
    font_header = get_font(24)
    font_text = get_font(28)
    
    text_x = 40
    if avatar_url:
        avt = get_cached_avatar(avatar_url, size=(80, 80), circle=True)
        if avt:
            try:
                img.paste(avt, (40, 30), avt)
                text_x = 140
            except Exception as e:
                print(f"⚠️ [PIL] paste avatar tong_ket_nha: {e}")
        
    draw.text((text_x, 45), f"TỔNG KẾT DOANH THU CÁC TÒA NHÀ HÔM NAY: {user_name.upper()}", font=font_title, fill="#f1c40f")
    draw.line([(40, 130), (1240, 130)], fill='#404249', width=3)
    
    headers = ["TÊN TÒA NHÀ", "S.L NV", "TỔNG CHI PHÍ", "THU NHẬP", "LỢI NHUẬN"]
    x_pos = [40, 350, 500, 780, 1020]
    for i, h in enumerate(headers):
        draw.text((x_pos[i], 150), h, font=font_header, fill="#bdc3c7")
        
    y = 210
    total_net = 0
    for biz_name, b_stat in stats.items():
        draw.text((x_pos[0], y), biz_name[:15] + ("..." if len(biz_name)>15 else ""), font=font_text, fill="#ffffff")
        draw.text((x_pos[1], y), str(b_stat.get("emp", 0)), font=font_text, fill="#3498db")
        
        cphi = b_stat.get("rent", 0) + b_stat.get("salary", 0)
        draw.text((x_pos[2], y), format_coin(cphi), font=font_text, fill="#e74c3c")
        
        gross_val = b_stat.get("gross", 0)
        draw.text((x_pos[3], y), format_coin(gross_val), font=font_text, fill="#2ecc71")
        
        net_val = b_stat.get("net", 0)
        net_color = "#2ecc71" if net_val > 0 else "#e74c3c"
        draw.text((x_pos[4], y), format_coin(net_val), font=font_text, fill=net_color)
        
        total_net += net_val
        y += 60
        
    draw.line([(40, y + 10), (1240, y + 10)], fill='#404249', width=3)
    net_total_color = "#2ecc71" if total_net > 0 else "#e74c3c"
    draw.text((40, y + 30), f"👉 TỔNG LỢI NHUẬN CÁC TÒA NHÀ HÔM NAY: {format_coin(total_net)}", font=font_title, fill=net_total_color)
    
    # 🚀 ÉP LÊN RAM
    buffered = BytesIO()
    # 💡 JPEG giảm size 60-70% so với PNG, tốc độ gửi Zalo nhanh hơn
    img.save(buffered, format="JPEG", quality=78)
    return base64.b64encode(buffered.getvalue()).decode('utf-8')
    
@_pil_offload
def tao_anh_xidach(user_name, p_hand, b_hand, p_score, b_score, p_status, b_status, is_game_over, img_result_msg, avatar_url=""):
    img = Image.new('RGB', (1200, 800), color='#1e1e24') 
    draw = ImageDraw.Draw(img)
    
    font_title = get_font(56)
    font_text = get_font(40)
    font_card_rank = get_font(48)
    font_card_suit = get_font(72)

    draw.rectangle([0, 0, 1200, 120], fill="#2b2d31")
    text_x = 40
    if avatar_url:
        avt = get_cached_avatar(avatar_url, size=(80, 80), circle=True)
        if avt:
            try:
                img.paste(avt, (40, 30), avt)
                text_x = 140
            except Exception as e:
                print(f"⚠️ [PIL] paste avatar xidach: {e}")
    draw.text((text_x, 30), f"SÒNG BÀI XÌ DÁCH", font=font_title, fill=(241, 196, 15))

    def draw_card(cx, cy, card_str, is_hidden=False):
        cw, ch = 140, 200 
        if is_hidden:
            draw.rounded_rectangle([cx, cy, cx+cw, cy+ch], radius=16, fill="#ffffff", outline="#bdc3c7", width=4)
            draw.rounded_rectangle([cx+10, cy+10, cx+cw-10, cy+ch-10], radius=10, fill="#e74c3c") 
            draw.text((cx+30, cy+70), "TEN", font=font_text, fill="#ffffff")
            return
            
        draw.rounded_rectangle([cx, cy, cx+cw, cy+ch], radius=16, fill="#ffffff", outline="#bdc3c7", width=4)
        rank = card_str[:-1]
        suit = card_str[-1]
        color = "#e74c3c" if suit in ['♥', '♦'] else "#2c3e50" 
        draw.text((cx+16, cy+10), rank, font=font_card_rank, fill=color)
        draw.text((cx+cw//2 - 24, cy+ch//2 - 30), suit, font=font_card_suit, fill=color)

    draw.text((40, 160), f"Nhà Cái Tẻn: {b_status if is_game_over else '???'}", font=font_text, fill=(236, 240, 241))
    start_x = 40
    for i, card in enumerate(b_hand):
        is_hidden_flag = not is_game_over and i > 0 
        draw_card(start_x + (i * 160), 220, card, is_hidden=is_hidden_flag)

    draw.text((40, 460), f"Người chơi ({user_name}): {p_status}", font=font_text, fill=(236, 240, 241))
    for i, card in enumerate(p_hand):
        draw_card(start_x + (i * 160), 520, card, is_hidden=False)

    draw.rectangle([0, 740, 1200, 800], fill="#2b2d31")
    res_color = "#2ecc71" if any(w in img_result_msg for w in ["THANG", "THẮNG", "HUP", "HÚP"]) else ("#e74c3c" if any(w in img_result_msg for w in ["THUA"]) else "#f1c40f")
    draw.text((40, 750), img_result_msg, font=font_text, fill=res_color)

    # 🚀 ÉP LÊN RAM
    buffered = BytesIO()
    # 💡 JPEG giảm size 60-70% so với PNG, tốc độ gửi Zalo nhanh hơn
    img.save(buffered, format="JPEG", quality=78)
    return base64.b64encode(buffered.getvalue()).decode('utf-8')

@_pil_offload
def tao_anh_baucua(user_name, choices, bet_per_face, results, net_profit, img_result_msg, avatar_url=""):
    img = Image.new('RGB', (1200, 800), color='#1e1e24') 
    draw = ImageDraw.Draw(img)
    
    font_title = get_font(64)
    font_text = get_font(40)
    font_large = get_font(55)
    font_mini = get_font(32)

    draw.rectangle([0, 0, 1200, 140], fill="#2b2d31")
    text_x = 40
    if avatar_url:
        avt = get_cached_avatar(avatar_url, size=(80, 80), circle=True)
        if avt:
            try:
                img.paste(avt, (40, 30), avt)
                text_x = 140
            except Exception as e:
                print(f"⚠️ [PIL] paste avatar baucua: {e}")
    draw.text((text_x, 35), f"{user_name.upper()}", font=font_title, fill=(241, 196, 15))

    def paste_icon(icon_name, x, y, size=48):
        icon_path = os.path.join(BASE_DIR, "icons", icon_name)
        try:
            icon_img = Image.open(icon_path).convert("RGBA")
            icon_img = icon_img.resize((size, size), Image.LANCZOS) 
            img.paste(icon_img, (x, y), icon_img)
        except Exception as e:
            print(f"⚠️ [PIL] paste_icon baucua {icon_name}: {e}")

    BAUCUA_FACES_ORDER = ['nai', 'gà', 'cá', 'bầu', 'cua', 'tôm']
    grid_area = [60, 160, 1140, 680]
    cell_w = (grid_area[2] - grid_area[0]) // 3
    cell_h = (grid_area[3] - grid_area[1]) // 2
    
    results_counts = {}
    for face in results:
        results_counts[face] = results_counts.get(face, 0) + 1

    for i, symbol in enumerate(BAUCUA_FACES_ORDER):
        row, col = divmod(i, 3)
        cx = grid_area[0] + (col * cell_w)
        cy = grid_area[1] + (row * cell_h)
        
        draw.rounded_rectangle([cx, cy, cx+cell_w, cy+cell_h], radius=16, fill=None, outline="#404249", width=3)
        
        icon_name = BAUCUA_ICONS.get(symbol)
        if icon_name: paste_icon(icon_name, cx + 50, cy + 50, size=200) 
            
        if symbol in choices:
            draw.rounded_rectangle([cx+5, cy+5, cx+cell_w-5, cy+cell_h-5], radius=12, fill=None, outline="#f1c40f", width=6)
            draw.text((cx + cell_w - 170, cy + cell_h - 60), f"#{format_coin(bet_per_face)}", font=font_mini, fill="#f1c40f")

        if results_counts.get(symbol, 0) > 0:
            draw.rounded_rectangle([cx+10, cy+10, cx+cell_w-10, cy+cell_h-10], radius=10, fill=None, outline="#2ecc71", width=10)
            if symbol in choices:
                draw.text((cx + 20, cy + 20), f"×{results_counts[symbol]}", font=font_large, fill="#2ecc71")

    draw.rectangle([0, 700, 1200, 800], fill="#2b2d31")
    res_color = "#2ecc71" if net_profit > 0 else ("#f1c40f" if net_profit == 0 else "#e74c3c")
    draw.text((60, 715), img_result_msg, font=font_title, fill=res_color)

    # 🚀 ÉP LÊN RAM
    buffered = BytesIO()
    # 💡 JPEG giảm size 60-70% so với PNG, tốc độ gửi Zalo nhanh hơn
    img.save(buffered, format="JPEG", quality=78)
    return base64.b64encode(buffered.getvalue()).decode('utf-8')
    
@_pil_offload
def tao_anh_altp(user_name, step, prize, q_data, lifelines, avatar_url=""):
    img = Image.new('RGB', (1200, 800), color='#08142b') 
    draw = ImageDraw.Draw(img)
    
    font_title = get_font(45)
    font_q = get_font(40)
    font_opt = get_font(35)
    font_badge = get_font(25)

    draw.rectangle([0, 0, 1200, 100], fill="#112240")
    text_x = 40
    if avatar_url:
        avt = get_cached_avatar(avatar_url, size=(80, 80), circle=True)
        if avt:
            try:
                img.paste(avt, (40, 30), avt)
                text_x = 140
            except Exception as e:
                print(f"⚠️ [PIL] paste avatar altp: {e}")
        
    draw.text((text_x, 25), f"AI LÀ TRIỆU PHÚ: {user_name.upper()}", font=font_title, fill="#f39c12")
    
    ll_y = 115
    draw.text((40, ll_y), "Quyền trợ giúp:", font=font_badge, fill="#bdc3c7")
    
    def draw_lifeline(x, name, is_active):
        color = "#f1c40f" if is_active else "#7f8c8d"
        bg = "#2c3e50" if is_active else "#1a252f"
        draw.rounded_rectangle([x, ll_y-5, x+160, ll_y+35], radius=10, fill=bg, outline=color, width=2)
        draw.text((x+15, ll_y), name, font=font_badge, fill=color)
        if not is_active:
            draw.line([(x+10, ll_y+15), (x+150, ll_y+15)], fill="#e74c3c", width=3) 
            
    draw_lifeline(240, "50 : 50", lifelines.get("5050", False))
    draw_lifeline(420, "Gọi N.Thân", lifelines.get("gdnt", False))
    draw_lifeline(600, "Chuyên Gia", lifelines.get("ntt", False))

    def get_text_width(text, font):
        if hasattr(font, 'getlength'): return font.getlength(text)
        elif hasattr(font, 'getbbox'): return font.getbbox(text)[2]
        return font.getsize(text)[0]

    q_box = [60, 160, 1140, 430]
    draw.rounded_rectangle(q_box, radius=20, fill="#112240", outline="#f39c12", width=4)
    
    words = str(q_data['q']).split()
    lines = []
    current_line = ""
    for word in words:
        test_line = current_line + word + " "
        if get_text_width(test_line, font_q) <= (q_box[2] - q_box[0] - 60):
            current_line = test_line
        else:
            lines.append(current_line)
            current_line = word + " "
    lines.append(current_line)

    line_spacing_q = 60 
    total_text_h = len(lines) * line_spacing_q
    start_y = q_box[1] + (q_box[3] - q_box[1] - total_text_h) // 2
    draw.text((110, 180), f"Câu {step} - Trị giá: {prize:,} xu".replace(',', '.'), font=font_q, fill="#2ecc71")
    for i, line in enumerate(lines):
        line_w = get_text_width(line, font_q)
        line_x = q_box[0] + (q_box[2] - q_box[0] - line_w) // 2
        draw.text((line_x, start_y + (i * line_spacing_q)), line.strip(), font=font_q, fill="#ffffff")

    opt_boxes = {
        "a": [60, 460, 580, 600],
        "b": [620, 460, 1140, 600],
        "c": [60, 630, 580, 770],
        "d": [620, 630, 1140, 770]
    }
    
    line_spacing_opt = 50 
    
    for key, box in opt_boxes.items():
        opt_text = str(q_data['opts'][key])
        if opt_text == "[Đã loại bỏ]":
            draw.rounded_rectangle(box, radius=20, fill="#1a252f", outline="#7f8c8d", width=2)
        else:
            draw.rounded_rectangle(box, radius=20, fill="#112240", outline="#3498db", width=4)
            draw.text((box[0] + 30, box[1] + 50), f"{key.upper()}.", font=font_title, fill="#f39c12")
            
            o_lines = []
            o_curr = ""
            for word in opt_text.split():
                t_line = o_curr + word + " "
                if get_text_width(t_line, font_opt) <= (box[2] - box[0] - 100): o_curr = t_line
                else: o_lines.append(o_curr); o_curr = word + " "
            o_lines.append(o_curr)
            
            o_start_y = box[1] + (box[3] - box[1] - len(o_lines)*line_spacing_opt) // 2
            for i, line in enumerate(o_lines):
                draw.text((box[0] + 100, o_start_y + (i * line_spacing_opt)), line.strip(), font=font_opt, fill="#ffffff")

    # 🚀 ÉP LÊN RAM
    buffered = BytesIO()
    # 💡 JPEG giảm size 60-70% so với PNG, tốc độ gửi Zalo nhanh hơn
    img.save(buffered, format="JPEG", quality=78)
    return base64.b64encode(buffered.getvalue()).decode('utf-8')
    
@_pil_offload
def tao_anh_vi(user_name, balance, income, expense, loan_limit, system_debt, p2p_data_user, history_data, avatar_url=""):
    width, height = 1307, 735
    path_bg = os.path.join(BASE_DIR, "background_card", "coin-card-bg.png")

    def paste_icon(icon_name, x, y):
        icon_path = os.path.join(BASE_DIR, "icons", icon_name)
        try:
            icon_img = Image.open(icon_path).convert("RGBA")
            icon_img = icon_img.resize((48, 48), Image.LANCZOS) 
            final_img.paste(icon_img, (x, y), icon_img)
        except Exception:
            # Fallback nếu thiếu file icon: vẽ hình tròn có viền
            icon_map = {"coin.png": "💰", "income.png": "📈", "outcome.png": "📉", "loan.png": "🏦"}
            symbol = icon_map.get(icon_name, "⭐")
            draw.ellipse([x, y, x + 44, y + 44], fill="#34495e", outline="#f1c40f", width=2)
            draw.text((x + 10, y + 6), symbol, font=get_font(24), fill="#ffffff")

    try:
        img_bg_orig = Image.open(path_bg).convert("RGBA")
        img_bg = img_bg_orig.resize((width, height), Image.LANCZOS)
    except Exception:
        # Fallback background nếu thiếu file coin-card-bg.png: vẽ thẻ màu tối hiện đại
        img_bg = Image.new('RGBA', (width, height), color='#1e1e24')
        d_bg = ImageDraw.Draw(img_bg)
        d_bg.rounded_rectangle([20, 20, width - 20, height - 20], radius=30, fill='#111827', outline='#3b82f6', width=4)
        
    final_img = img_bg.convert("RGB")
    draw = ImageDraw.Draw(final_img)
    
    font_title = get_font(60)
    font_text = get_font(40)
    font_large = get_font(70)

    draw.text((680, 150), f"{user_name}", font=font_text, fill=(185, 187, 190), anchor="rm")
    draw.line([(80, 180), (680, 180)], fill=(185, 187, 190), width=2)

    paste_icon("coin.png", 80, 350)
    draw.text((150, 350), f"{balance:,}".replace(',', '.'), font=font_text, fill=(185, 187, 190), stroke_width=1)
    
    paste_icon("income.png", 80, 400)
    draw.text((150, 400), f"+{income:,}".replace(',', '.'), font=font_text, fill=(185, 187, 190), stroke_width=1)
    paste_icon("outcome.png", 80, 450)
    draw.text((150, 450), f"-{expense:,}".replace(',', '.'), font=font_text, fill=(185, 187, 190), stroke_width=1)
    
    paste_icon("loan.png", 80, 500)
    draw.text((150, 500), f"Hạn mức vay: {loan_limit:,}".replace(',', '.'), font=font_text, fill=(185, 187, 190), stroke_width=1)
    
    debt_y = 550
    has_debt = False
    if system_debt > 0:
        has_debt = True
        draw.text((80, 550), f"Nợ hệ thống: {system_debt:,}".replace(',', '.'), font=font_text, fill=(185, 187, 190), stroke_width=1)
        debt_y += 45
        
    for lender, p_loan in p2p_data_user.items():
        if debt_y > 670:
            draw.text((80, debt_y), f"• ... và các khoản nợ P2P khác.", font=font_text, fill=(185, 187, 190), stroke_width=1)
            has_debt = True
            break
        has_debt = True
        draw.text((80, debt_y), f"Trả {lender}: {p_loan['remaining']:,} xu".replace(',', '.'), font=font_text, fill=(185, 187, 190), stroke_width=1)
        debt_y += 45
        
    if not has_debt:
        draw.text((80, debt_y), "", font=font_text, fill=(87, 242, 135))

    chart_x, chart_y = 670, 200
    chart_w, chart_h = 580, 490
    
    draw.rounded_rectangle([chart_x, chart_y, chart_x+chart_w, chart_y+chart_h], radius=20, fill=(0, 0, 0, 130), outline=(255, 255, 255, 40), width=2)
    draw.text((chart_x + 30, chart_y + 20), "Biến động số dư", font=font_text, fill=(255, 255, 255))
    
    max_val = max(history_data) if max(history_data) > 0 else 1
    bar_w = 70
    gap = 70
    start_bar_x = chart_x + (chart_w - (3 * bar_w + 2 * gap)) // 2
    base_y = chart_y + chart_h - 60
    labels = ["-2h", "-1h", "Hiện tại"]
    
    for i, val in enumerate(history_data):
        b_h = int((val / max_val) * (chart_h - 200))
        if b_h < 5: b_h = 5 
        
        bx = start_bar_x + i * (bar_w + gap)
        by = base_y - b_h
        
        bar_color = (88, 101, 242) if i == 2 else (87, 242, 135)
        draw.rounded_rectangle([bx, by, bx+bar_w, base_y], radius=8, fill=bar_color)
        
        val_str = f"{val/1000000:.1f}m" if val >= 1000000 else (f"{val/1000:.1f}k" if val >= 1000 else str(val))
        try: val_w = font_text.getlength(val_str)
        except: val_w = font_text.getsize(val_str)[0]
        
        draw.text((bx + (bar_w - val_w)//2, by - 45), val_str, font=font_text, fill=(255, 255, 255))
        
        try: lbl_w = font_text.getlength(labels[i])
        except: lbl_w = font_text.getsize(labels[i])[0]
        draw.text((bx + (bar_w - lbl_w)//2, base_y + 10), labels[i], font=font_text, fill=(185, 187, 190))

    # 🚀 ÉP LÊN RAM
    buffered = BytesIO()
    # 💡 JPEG giảm size 60-70% so với PNG, tốc độ gửi Zalo nhanh hơn
    final_img.save(buffered, format="JPEG", quality=78)
    return base64.b64encode(buffered.getvalue()).decode('utf-8')

def check_winner_caro(board):
    for r in range(6):
        for c in range(6):
            p = board[r][c]
            if p == ' ': continue
            if c <= 1 and board[r][c+1] == p and board[r][c+2] == p and board[r][c+3] == p and board[r][c+4] == p: return p
            if r <= 1 and board[r+1][c] == p and board[r+2][c] == p and board[r+3][c] == p and board[r+4][c] == p: return p
            if r <= 1 and c <= 1 and board[r+1][c+1] == p and board[r+2][c+2] == p and board[r+3][c+3] == p and board[r+4][c+4] == p: return p
            if r <= 1 and c >= 4 and board[r+1][c-1] == p and board[r+2][c-2] == p and board[r+3][c-3] == p and board[r+4][c-4] == p: return p
    return None

def is_board_full_caro(board):
    for row in board:
        if ' ' in row: return False
    return True

def bot_move_caro(board, bot_piece, player_piece):
    for r in range(6):
        for c in range(6):
            if board[r][c] == ' ':
                board[r][c] = bot_piece
                if check_winner_caro(board) == bot_piece: return r, c
                board[r][c] = ' '
    for r in range(6):
        for c in range(6):
            if board[r][c] == ' ':
                board[r][c] = player_piece
                if check_winner_caro(board) == player_piece:
                    board[r][c] = ' '
                    return r, c
                board[r][c] = ' '
    centers = [(2,2), (2,3), (3,2), (3,3), (1,2), (1,3), (4,2), (4,3), (2,1), (3,1), (2,4), (3,4)]
    for r, c in centers:
        if board[r][c] == ' ': return r, c
    empty_cells = [(r, c) for r in range(6) for c in range(6) if board[r][c] == ' ']
    if empty_cells: return random.choice(empty_cells)
    return None, None

@_pil_offload
def tao_anh_caro(p1_name, p2_name, board, bet_amt, status_msg, turn_piece):
    width, height = 900, 900
    img = Image.new('RGB', (width, height), color='#2b2d31')
    draw = ImageDraw.Draw(img)
    
    font_title = get_font(45)
    font_text = get_font(35)
    font_xo = get_font(65)
    font_label = get_font(30)

    draw.rectangle([0, 0, width, 120], fill="#1e1e24")
    draw.text((40, 20), f"⚔️ TRẬN CHIẾN CARO (6x6) ⚔️", font=font_title, fill="#f1c40f")
    draw.text((40, 70), f"Cược: {bet_amt:,} xu | {p1_name} (X) vs {p2_name} (O)".replace(',', '.'), font=font_text, fill="#ecf0f1")

    grid_size = 600
    cell_size = grid_size // 6
    start_x = 200
    start_y = 160

    draw.rounded_rectangle([start_x, start_y, start_x + grid_size, start_y + grid_size], radius=15, fill="#112240", outline="#3498db", width=6)

    for i in range(1, 6):
        draw.line([(start_x + i * cell_size, start_y), (start_x + i * cell_size, start_y + grid_size)], fill="#3498db", width=3)
        draw.line([(start_x, start_y + i * cell_size), (start_x + grid_size, start_y + i * cell_size)], fill="#3498db", width=3)

    rows_label = ['A', 'B', 'C', 'D', 'E', 'F']
    cols_label = ['1', '2', '3', '4', '5', '6']
    for i in range(6):
        draw.text((start_x - 40, start_y + i * cell_size + cell_size//2 - 20), rows_label[i], font=font_label, fill="#e74c3c")
        draw.text((start_x + i * cell_size + cell_size//2 - 10, start_y - 45), cols_label[i], font=font_label, fill="#2ecc71")

    for r in range(6):
        for c in range(6):
            piece = board[r][c]
            if piece != ' ':
                color = "#e74c3c" if piece == 'X' else "#2ecc71"
                cx = start_x + c * cell_size + cell_size // 2
                cy = start_y + r * cell_size + cell_size // 2 - 10
                try: w = font_xo.getlength(piece)
                except: w = font_xo.getsize(piece)[0]
                draw.text((cx - w//2, cy - 35), piece, font=font_xo, fill=color)

    res_color = "#f1c40f" if "THẮNG" in status_msg or "HÒA" in status_msg else "#ffffff"
    draw.rectangle([0, height-100, width, height], fill="#1e1e24")
    draw.text((40, height-75), status_msg, font=font_text, fill=res_color)

    # 🚀 ÉP LÊN RAM
    buffered = BytesIO()
    # 💡 JPEG giảm size 60-70% so với PNG, tốc độ gửi Zalo nhanh hơn
    img.save(buffered, format="JPEG", quality=78)
def init_browser(headless=False):
    r"""
    Khởi tạo Selenium Chrome với profile lưu tại local d:\zalobot\chrome_profile_zalo
    Duy trì đăng nhập Zalo Web tự động mà không cần quét mã QR lại nhiều lần.
    """
    options = webdriver.ChromeOptions()
    user_data = os.path.join(BASE_DIR, "chrome_profile_zalo")
    options.add_argument(f"--user-data-dir={user_data}")
    options.add_argument("--disable-notifications")
    options.add_argument("--disable-infobars")
    options.add_argument("--mute-audio")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option("useAutomationExtension", False)

    if headless:
        options.add_argument("--headless=new")
        options.add_argument("--disable-gpu")
        options.add_argument("--disable-software-rasterizer")

    try:
        service = Service(ChromeDriverManager().install())
        driver = webdriver.Chrome(service=service, options=options)
    except Exception as e:
        print(f"⚠️ [Browser] ChromeDriverManager error: {e}. Thử khởi tạo trực tiếp...")
        driver = webdriver.Chrome(options=options)

    driver.set_window_size(1280, 850)
    driver.get("https://chat.zalo.me/")
    return driver


def gui_tin_nhan_zalo(driver, text):
    try:
        driver.execute_script("""
            let closeBtn = document.querySelector('.quote-banner__close');
            if(closeBtn) closeBtn.click();
        """)
    except Exception:
        pass  # Không có quote banner — bỏ qua

    for i in range(2):
        try:
            input_box = driver.find_element(By.ID, "richInput")
            input_box.click()
            input_box.send_keys(Keys.CONTROL, "a")
            input_box.send_keys(Keys.DELETE)
            
            js_paste = """
            const text = arguments[0];
            const dataTransfer = new DataTransfer();
            dataTransfer.setData('text', text);
            const event = new ClipboardEvent('paste', {
              clipboardData: dataTransfer,
              bubbles: true
            });
            document.getElementById('richInput').dispatchEvent(event);
            """
            driver.execute_script(js_paste, text)
            
            time.sleep(0.5) 
            # 🧠 FIX ZALO ĐỔI NÚT GỬI:
            try:
              driver.find_element(By.CSS_SELECTOR, ".send-msg-btn").click()
            except:
              input_box.send_keys(Keys.ENTER)
              
            # 🧠 THÊM LẠI CÁI CHỐT NÀY VÀO! THÀNH CÔNG RỒI THÌ PHẢI DỪNG VÒNG LẶP!
            return True 
            
        except: time.sleep(0.5) 
    return False

def main():
    global driver
    load_altp_questions()
    get_gold_prices()
    init_font_cache()       # 🔤 Load toàn bộ font vào RAM 1 lần
    get_inventory_data()    # 📦 Load inventory vào RAM cache 1 lần
    
    # ⚡ Khởi động DB writer thread
    threading.Thread(target=_db_writer_thread, daemon=True).start()
    print("✅ DB writer thread đã khởi động.")
    
    driver = init_browser(headless=False)
    threading.Thread(target=admin_console_thread, daemon=True).start()
    
    print("⏳ Đang kiên nhẫn chờ sếp quét mã QR đăng nhập Zalo...")
    logged_in = False
    qr_path = os.path.join(BASE_DIR, "zalo_qr.png")
    while not logged_in:
        try:
            search_box = WebDriverWait(driver, 3).until(EC.presence_of_element_located((By.ID, "contact-search-input")))
            time.sleep(1)
            search_box.clear()
            search_box.send_keys(TEN_NHOM_CHAT)
            time.sleep(2)
            search_box.send_keys(Keys.ENTER)
            logged_in = True
            print(f"✅ ĐÃ ĐĂNG NHẬP ZALO THÀNH CÔNG! Đã vào nhóm: '{TEN_NHOM_CHAT}'")
            if os.path.exists(qr_path):
                try:
                    os.remove(qr_path)
                except Exception:
                    pass
        except Exception:
            # Nếu chưa đăng nhập, chụp ảnh màn hình Zalo để lấy mã QR
            try:
                driver.save_screenshot(qr_path)
                print(f"📸 Đã cập nhật ảnh QR đăng nhập tại: {qr_path}")
            except Exception as se:
                print(f"⚠️ Không thể chụp ảnh Zalo QR: {se}")
            time.sleep(5)

    print("🚀 Tẻn đã sẵn sàng! Có thể gõ lệnh /hoanxu hoặc /addg ngay tại cửa sổ này.")
    gui_tin_nhan_zalo(driver, random.choice(STARTUP_MESSAGES))

    last_processed_msg_id = None
    last_other_sender = "Bạn" 
    
    user_msg_counts = load_json_data(DATA_FILE, {}) 
    tarot_data = load_json_data(TAROT_FILE, {})
    coin_data = load_json_data(COIN_FILE, {})
    # Khởi tạo ví xu riêng của bot nếu chưa có
    if BOT_NAME not in coin_data:
        coin_data[BOT_NAME] = BOT_DEFAULT_BALANCE
        save_json_data(COIN_FILE, coin_data)
        print(f"💰 Đã tạo ví bot '{BOT_NAME}' với số dư {BOT_DEFAULT_BALANCE:,} xu.")
    loan_data = load_json_data(LOAN_FILE, {})
    credit_data = load_json_data(CREDIT_FILE, {}) 
    jobs_data = load_json_data(JOBS_FILE, {}) 
    player_streaks = load_json_data(STREAKS_FILE, {}) 
    business_config = load_json_data(BUSINESS_FILE, DEFAULT_BUSINESS_CONFIG)
    assets_data = load_json_data(ASSETS_FILE, {})
    p2p_data = load_json_data(P2P_FILE, {})
    gold_data = load_json_data(GOLD_FILE, {})
    altp_winners_data = load_json_data(ALTP_WINNERS_FILE, {})
    profile_data = load_json_data(PROFILE_FILE, {})
    user_avatars = load_json_data(AVATAR_FILE, {}) 

    pending_loans = {}
    altp_games = {} 
    pending_p2p = {} 
    caro_games = {}
    pending_caro = {}
    
    last_morning_greet_date = None
    last_business_summary_date = None
    last_news_dates = {} 
    last_config_check_time = 0
    last_loan_check_time = time.time()
    last_job_check_time = time.time()
    last_altp_check_time = time.time()
    last_business_check_time = time.time()
    last_p2p_check_time = time.time()
    last_health_regen_time = time.time()
    last_hourly_snapshot = time.time()
    bot_config = load_bot_config()
    last_caro_check_time = time.time()
    last_auto_save_time = time.time()

    def parse_time(time_str, def_h, def_m):
        try: return datetime.datetime.strptime(time_str, "%I:%M %p").time()
        except: return datetime.time(def_h, def_m)
        
    market_data = load_json_data(MARKET_FILE, {
        "last_update": time.time(),
        "current": {"th": 750, "qa": 750, "xd": 750},
        "previous": {"th": 750, "qa": 750, "xd": 750}
    })

    # ⚙️ KHỞI TẠO BỘ ĐẾM NHỊP TIM HỆ THỐNG
    last_system_tick = time.time()

    while True:
        try:
            now = datetime.datetime.now()
            current_ts = time.time()

            # ==============================================================================
            # 🚀 GEAR 1: XỬ LÝ SIÊU TỐC LỆNH ADMIN CONSOLE
            # ==============================================================================

            while not admin_cmd_queue.empty():
                cmd = admin_cmd_queue.get()
                parts = cmd.split()
                try:
                    if cmd.startswith("/xd"):
                        global global_xd_mode
                        if cmd == "/xd1": global_xd_mode = 1; print("✅ Đã chuyển Xì Dách sang DỄ.")
                        elif cmd == "/xd2": global_xd_mode = 2; print("✅ Đã chuyển Xì Dách sang THƯỜNG.")
                        elif cmd == "/xd3": global_xd_mode = 3; print("✅ Đã chuyển Xì Dách sang KHÓ.")
                    elif cmd.startswith("/hoanxu "):
                        amount = int(parts[-1])
                        name = " ".join(parts[1:-1]).replace("*", "").replace("@", "").strip()
                        coin_data[name] = coin_data.get(name, 0) + amount
                        save_json_data(COIN_FILE, coin_data)
                        gui_tin_nhan_zalo(driver, f"💳 [HỆ THỐNG] Ngân hàng Tẻn đã hoàn trả {format_coin(amount)} cho {name} do sự cố chuyển nhầm!")
                        print(f"✅ Đã hoàn {amount} xu cho {name}.")
                    elif cmd.startswith("/addg "):
                        amount = int(parts[-1])
                        name = " ".join(parts[1:-1]).replace("*", "").replace("@", "").strip()
                        if name not in gold_data: gold_data[name] = {"nhan": 0, "mieng": 0, "last_trade": 0}
                        gold_data[name]["nhan"] = gold_data[name].get("nhan", 0) + amount
                        save_json_data(GOLD_FILE, gold_data)
                        gui_tin_nhan_zalo(driver, f"🎁 [PHÁT LỘC] Tẻn đã lì xì {amount} lượng Vàng Nhẫn cho @{name}!")
                        print(f"✅ Đã phát {amount} vàng cho {name}.")
                    elif cmd.startswith("/rsxu "):
                        name = " ".join(parts[1:]).replace("*", "").replace("@", "").strip()
                        name = find_exact_name(name, coin_data)
                        coin_data[name] = 0
                        save_json_data(COIN_FILE, coin_data)
                        gui_tin_nhan_zalo(driver, f"⚖️ [QUYẾT ĐỊNH ÂN XÁ]\nAdmin đã xóa sạch nợ xấu, reset ví của {name} về 0 xu để làm lại cuộc đời!")
                        print(f"✅ Đã reset xu cho {name}.")
                    elif cmd.startswith("/gt all "):
                        name = " ".join(parts[2:]).replace("*", "").replace("@", "").strip()
                        name = find_exact_name(name, assets_data)
                        if name in assets_data and assets_data[name].get("businesses"):
                            total_refund = sum(b["von"] // 2 for b in assets_data[name]["businesses"])
                            count = len(assets_data[name]["businesses"])
                            assets_data[name]["businesses"] = []
                            save_json_data(ASSETS_FILE, assets_data)
                            coin_data[name] = coin_data.get(name, 0) + total_refund
                            save_json_data(COIN_FILE, coin_data)
                            gui_tin_nhan_zalo(driver, f"💥 [LỆNH CƯỠNG CHẾ QUY HOẠCH]\nAdmin đã đập bỏ và giải thể TOÀN BỘ {count} tòa nhà/cơ sở bị bỏ hoang của {name}!\n💰 Thu hồi vật liệu và hoàn lại {format_coin(total_refund)} vào ví.")
                            print(f"✅ Đã cưỡng chế giải thể toàn bộ tài sản của {name}, hoàn {total_refund} xu.")
                        else:
                            gui_tin_nhan_zalo(driver, f"❌ [HỆ THỐNG] {name} đang vô sản, không có công trình nào để đập phá cả!")
                except Exception as e:
                    print(f"❌ Lỗi lệnh admin: {e}")



            # ==============================================================================
            # ⚙️ GEAR 2: LỤC PHỦ NGŨ TẠNG CRONJOB (CHỈ CHẠY 1 LẦN / GIÂY ĐỂ TRÁNH LAG CPU)
            # ==============================================================================
            if current_ts - last_system_tick >= 1.0:
                last_system_tick = current_ts
                
                # --- 💾 HỆ THỐNG LƯU FILE ĐỊNH KỲ (Giảm tải ổ cứng) ---
                if current_ts - last_auto_save_time > 60: 
                    save_json_data(COIN_FILE, coin_data)
                    save_json_data(DATA_FILE, user_msg_counts)
                    last_auto_save_time = current_ts

                    
                # --- KIỂM TRA TIMEOUT CARO (QUÁ 5 PHÚT BỊ XỬ THUA) ---
                if current_ts - last_caro_check_time > 10:
                    last_caro_check_time = current_ts
                    caro_to_remove = []
                    for g_id, g in list(caro_games.items()):
                        if current_ts - g["last_time"] > 300: 
                            current_turn_player = g["p1"] if g["turn"] == 'X' else g["p2"]
                            winner_player = g["p2"] if g["turn"] == 'X' else g["p1"]
                            
                            if g["type"] == "PvP":
                                coin_data[winner_player] += g["bet"] * 2
                                save_json_data(COIN_FILE, coin_data)
                                msg = f"⏰ TÍT TÍT! {current_turn_player} đã treo máy quá 5 phút trong trận Caro!\n🏆 XỬ THUA MẶC ĐỊNH! {winner_player} được cộng {format_coin(g['bet']*2)}."
                            else:
                                msg = f"⏰ TÍT TÍT! {current_turn_player} nhát gan treo máy bỏ chạy khi đang đấu Caro với Tẻn!\n💀 Đã bị tịch thu {format_coin(g['bet'])} tiền cược."
                                
                            gui_tin_nhan_zalo(driver, msg)
                            caro_to_remove.append(g_id)
                            
                    for r in caro_to_remove: del caro_games[r]
                    
                # --- 🕒 CHỐT SỔ VÍ TIỀN MỖI 1 GIỜ ---
                if current_ts - last_hourly_snapshot > 3600:
                    last_hourly_snapshot = current_ts
                    wallet_stats = load_json_data("wallet_data.json", {})
                    
                    for p_user, p_bal in coin_data.items():
                        if p_user not in wallet_stats:
                            wallet_stats[p_user] = {"income": 0, "expense": 0, "history": [p_bal, p_bal, p_bal]}
                        
                        user_stat = wallet_stats[p_user]
                        old_bal = user_stat["history"][-1]
                        diff = p_bal - old_bal
                        
                        if diff > 0: user_stat["income"] += diff
                        elif diff < 0: user_stat["expense"] += abs(diff)
                        
                        user_stat["history"].append(p_bal)
                        if len(user_stat["history"]) > 3:
                            user_stat["history"].pop(0)
                            
                    save_json_data("wallet_data.json", wallet_stats)

                if current_ts - last_p2p_check_time > 10:
                    last_p2p_check_time = current_ts
                    for borrower, lenders in list(p2p_data.items()):
                        for lender, p_loan in list(lenders.items()):
                            if p_loan["remaining"] <= 0:
                                del p2p_data[borrower][lender]; continue
                                
                            if p_loan["status"] == "ACTIVE" and current_ts > p_loan["deadline"]:
                                if not p_loan.get("notified"):
                                    p_loan["notified"] = True
                                    p_loan["seizable_time"] = current_ts + 300 
                                    save_json_data(P2P_FILE, p2p_data)
                                    msg = f"⚠️ BÁO ĐỘNG ĐỎ TRẢ NỢ P2P ⚠️\nÊ {borrower}, tới hạn trả {format_coin(p_loan['remaining'])} cho chủ nợ {lender} rồi kìa!\n⏳ Ông có 5 phút để xoay xở (gõ /tratien @{lender} [số tiền])."
                                    gui_tin_nhan_zalo(driver, msg)
                                    
                                elif current_ts > p_loan.get("seizable_time", 0):
                                    p_loan["status"] = "SEIZABLE"
                                    save_json_data(P2P_FILE, p2p_data)
                                    msg = f"🪓 ĐÃ HẾT 5 PHÚT ÂN HẠN!\n👉 Chủ nợ {lender} có thể gõ lệnh '/sietno @{borrower}' để tịch thu 85% ví, cướp vàng và đập phá nhà xưởng của con nợ!"
                                    gui_tin_nhan_zalo(driver, msg)
                                
                    empty_borrowers = [b for b in p2p_data if not p2p_data[b]]
                    for b in empty_borrowers: del p2p_data[b]
                    if empty_borrowers: save_json_data(P2P_FILE, p2p_data)

                # --- KIỂM TRA BIẾN ĐỘNG THỊ TRƯỜNG VẬT LIỆU ---
                if current_ts - market_data.get("last_update", 0) > 18000:
                    market_data["previous"] = market_data["current"].copy()
                    market_data["current"] = {
                        "th": random.randint(500, 1000),
                        "qa": random.randint(500, 1000),
                        "xd": random.randint(500, 1000)
                    }
                    market_data["last_update"] = current_ts
                    save_json_data(MARKET_FILE, market_data)

                # --- KIỂM TRA LÃI CƠ SỞ KINH DOANH ---
                if current_ts - last_business_check_time > 10:
                    last_business_check_time = current_ts
                    payout_msgs = []
                    inventory_data = get_inventory_data()
                    changed_inv = False

                    for player, assets in list(assets_data.items()):
                        if "businesses" in assets:
                            businesses_to_remove = []
                            if player not in inventory_data: inventory_data[player] = {}
                            user_inv = inventory_data[player]
                            if "materials" not in user_inv: user_inv["materials"] = {"th": 0, "qa": 0, "xd": 0}
                            
                            used_management = 0.0
                            for b in assets["businesses"]:
                                b_qm_id = int(b.get("id_quy_mo", 1))
                                if b.get("id_nganh") == "xd": used_management += 2 if b_qm_id <= 2 else 3
                                else: used_management += 1 if b_qm_id <= 2 else 2
                                used_management += b.get("employees", 0) * 0.5
                                
                            pf = get_profile(player, profile_data)
                            is_overloaded = used_management > pf["management_limit"]
                            
                            for i, b in enumerate(assets["businesses"]):
                                last_payout_time = b.get("last_payout", current_ts)
                                if "last_payout" not in b: b["last_payout"] = current_ts
                                    
                                if current_ts - last_payout_time >= b.get("thoi_gian", 18000):
                                    b["last_payout"] = current_ts 
                                    base_lai = b.get("lai", 0)
                                    qm_id = int(b.get("id_quy_mo", 1))
                                    nganh = b.get("id_nganh")
                                    
                                    if base_lai <= 0: continue
                                    
                                    emp = b.get("employees", 0)
                                    max_emp = MAX_EMP.get(qm_id, 2)
                                    rent_cost = int(b.get("von", 0) * 0.05) 
                                    salary_cost = int(base_lai * 0.02 * emp) 
                                    
                                    efficiency = 0.05 + 0.95 * (emp / max_emp)
                                    gross_profit = int(base_lai * efficiency)
                                    
                                    is_halted = False
                                    if nganh in ["th", "qa", "xd"]:
                                        req_mat = MAT_USAGE.get(qm_id, 15)
                                        if user_inv["materials"].get(nganh, 0) < req_mat:
                                            is_halted = True
                                        else:
                                            user_inv["materials"][nganh] -= req_mat
                                            changed_inv = True
                                    elif nganh == "nh":
                                        tax_cost = int(base_lai * 0.05)
                                        if b.get("bank_reserves", 0) < tax_cost:
                                            is_halted = True
                                        else:
                                            b["bank_reserves"] -= tax_cost
                                    
                                    if is_halted:
                                        coin_data[player] = coin_data.get(player, 0) - rent_cost
                                        add_daily_stat(player, b.get('ten'), emp, rent_cost, 0, 0, -rent_cost)
                                        continue
                                    
                                    disaster_chance = 5 + (15 if is_overloaded else 0)
                                    disaster_roll = random.randint(1, 100)
                                    if disaster_roll <= disaster_chance:
                                        coin_data[player] = coin_data.get(player, 0) - rent_cost - salary_cost
                                        dtype = random.choice([1, 2, 3])
                                        if dtype == 1:
                                            payout_msgs.append(f"🔥 TIN BUỒN! '{b.get('ten')}' của {player} bị chập điện cháy rụi. Khởi nghiệp thất bại!")
                                            businesses_to_remove.append(i)
                                        elif dtype == 2:
                                            phat = b.get("von", 0) // 2
                                            coin_data[player] = coin_data.get(player, 0) - phat
                                            payout_msgs.append(f"🚓 BIẾN CĂNG! '{b.get('ten')}' bị phạt {format_coin(phat)} vì quản lý lỏng lẻo!")
                                        else:
                                            coin_data[player] = coin_data.get(player, 0) - (base_lai * 2)
                                            payout_msgs.append(f"🏃 ĐEN QUÁ! Nhân viên ôm {format_coin(base_lai * 2)} bỏ trốn!")
                                        continue
                                    
                                    fluct_roll = random.randint(1, 100)
                                    if fluct_roll <= 20: gross_profit = int(gross_profit * random.uniform(1.2, 1.5))
                                    elif fluct_roll <= 70: gross_profit = int(gross_profit * random.uniform(0.7, 1.0))
                                    elif fluct_roll <= 90: 
                                        gross_profit = int(gross_profit * random.uniform(0.2, 0.5))
                                        if is_overloaded: gross_profit = gross_profit // 2
                                    else:
                                        gross_profit = -int(gross_profit * random.uniform(0.1, 0.3))
                                        if is_overloaded: gross_profit = gross_profit * 2
                                    
                                    net_profit = gross_profit - rent_cost - salary_cost
                                    coin_data[player] = coin_data.get(player, 0) + net_profit
                                    add_daily_stat(player, b.get('ten'), emp, rent_cost, salary_cost, gross_profit, net_profit)
                                            
                            for i in sorted(businesses_to_remove, reverse=True):
                                assets["businesses"].pop(i)
                                
                    if changed_inv: save_inventory_data()
                    if payout_msgs:
                        save_json_data(COIN_FILE, coin_data)
                        save_json_data(ASSETS_FILE, assets_data)
                        for m in payout_msgs: gui_tin_nhan_zalo(driver, m)

                if current_ts - last_altp_check_time > 2:
                    last_altp_check_time = current_ts
                    for player, game in list(altp_games.items()):
                        if current_ts > game["end_time"]:
                            if game["state"] == "WAITING_START":
                                coin_data[player] = coin_data.get(player, 0) + 50
                                save_json_data(COIN_FILE, coin_data)
                                gui_tin_nhan_zalo(driver, f"⏰ Đã quá 60s mà không xác nhận, {player} bị mời ra ngoài (Hoàn lại 50 xu)!")
                                del altp_games[player]
                            elif game["state"] == "PLAYING":
                                safe_prize = 0
                                if game["step"] > 10: safe_prize = 20000
                                elif game["step"] > 5: safe_prize = 1000
                                if safe_prize > 0:
                                    coin_data[player] = coin_data.get(player, 0) + safe_prize
                                    save_json_data(COIN_FILE, coin_data)
                                msg = f"⏰ Tít tít! Đã hết thời gian 25s suy nghĩ! {player} bị loại.\n"
                                if safe_prize > 0: msg += f"💰 Nhận được mốc an toàn: {format_coin(safe_prize)}."
                                else: msg += f"💸 Trắng tay! {random.choice(ALTP_LOSE_MESSAGES)}"
                                pf = get_profile(player, profile_data); pf["stress"] = max(0, pf.get("stress", 0) - 25); save_json_data(PROFILE_FILE, profile_data)
                                msg += f"\n💆 Stress giảm 25 điểm."
                                gui_tin_nhan_zalo(driver, msg)
                                del altp_games[player]

                if current_ts - last_health_regen_time > 60:
                    last_health_regen_time = current_ts
                    updated_profile = False
                    training_msgs = []
                    
                    for player, pf in list(profile_data.items()):
                        if pf.get("training") and current_ts >= pf["training"]["end_time"]:
                            t_type = pf["training"]["type"]
                            boost = pf["training"]["boost"]
                            pf["max_health"] += boost
                            if pf["max_health"] > 100: pf["max_health"] = 100 
                            pf["health"] = min(pf["health"] + boost, pf["max_health"])
                            pf["training"] = None
                            updated_profile = True
                            training_msgs.append(f"💪 Ting ting! {player} đã hoàn thành buổi {t_type}! Giới hạn Sức khỏe vĩnh viễn tăng thêm {boost} (Max SK: {pf['max_health']}).")
                        
                        if pf.get("health", 0) < pf.get("max_health", 25):
                            pf["health"] = min(pf["health"] + 1, pf["max_health"])
                            updated_profile = True
                            
                    if updated_profile:
                        save_json_data(PROFILE_FILE, profile_data)
                        for tm in training_msgs:
                            gui_tin_nhan_zalo(driver, tm)

                if current_ts - last_job_check_time > 5:
                    last_job_check_time = current_ts
                    completed_jobs = []
                    for player, job_info in list(jobs_data.items()):
                        if current_ts >= job_info["end_time"]:
                            reward = job_info["reward"]; jname = job_info["job_name"]
                            coin_data[player] = coin_data.get(player, 0) + reward
                            completed_jobs.append(f"🎉 Ting Ting! {player} đã hoàn thành nhiệm vụ {jname} và nhận được lương {format_coin(reward)}!")
                            del jobs_data[player]
                    if completed_jobs:
                        save_json_data(COIN_FILE, coin_data); save_json_data(JOBS_FILE, jobs_data)
                        for cmsg in completed_jobs: gui_tin_nhan_zalo(driver, cmsg)
                
                if current_ts - last_loan_check_time > 10:
                    last_loan_check_time = current_ts
                    for player, loan_info in list(loan_data.items()):
                        remaining = loan_info["remaining"]
                        if remaining <= 0: del loan_data[player]; save_json_data(LOAN_FILE, loan_data); continue
                        deadline = loan_info["deadline"]
                        warned = loan_info.get("warned", False)
                        seizing = loan_info.get("seizing", False)
                        last_seize_time = loan_info.get("last_seize_time", 0)
                        
                        if not warned and current_ts > deadline:
                            msg = f"⚠️ CẢNH BÁO ĐÒI NỢ (HỆ THỐNG) ⚠️\nÊ {player}, tới hạn trả {format_coin(remaining)} rồi!\nCho 5 phút chuẩn bị tiền, không trả là Tẻn siết sạch từ tiền mặt, bán vàng tới tài sản cửa hàng nha!"
                            if gui_tin_nhan_zalo(driver, msg):
                                loan_info["warned"] = True; loan_info["last_seize_time"] = current_ts; save_json_data(LOAN_FILE, loan_data)
                                
                        elif warned and ((not seizing and current_ts > last_seize_time + 300) or (seizing and current_ts > last_seize_time + 14400)):
                            loan_info["seizing"] = True
                            balance = coin_data.get(player, 0)
                            
                            take_cash = min(balance, remaining) if balance > 0 else 0
                            if take_cash > 0:
                                coin_data[player] -= take_cash
                                remaining -= take_cash
                                
                            seized_gold_msg = ""
                            if remaining > 0 and player in gold_data:
                                gp = get_gold_prices()
                                if gp:
                                    u_gold = gold_data[player]
                                    for g_type, g_price in [("nhan", gp.get("nhan_mua", 0)), ("mieng", gp.get("mieng_mua", 0))]:
                                        g_taken = 0
                                        while remaining > 0 and u_gold.get(g_type, 0) > 0:
                                            u_gold[g_type] -= 1
                                            g_taken += 1
                                            if g_price >= remaining:
                                                refund = g_price - remaining
                                                coin_data[player] = coin_data.get(player, 0) + refund
                                                remaining = 0
                                            else:
                                                remaining -= g_price
                                        if g_taken > 0:
                                            g_name = "Vàng Nhẫn" if g_type == "nhan" else "Vàng Miếng"
                                            seized_gold_msg += f"🪙 Tịch thu {g_taken} lượng {g_name}.\n"
                                    save_json_data(GOLD_FILE, gold_data)
                                    
                            seized_biz = []
                            refund = 0
                            if remaining > 0 and player in assets_data and assets_data[player].get("businesses"):
                                assets = assets_data[player]["businesses"]
                                assets.sort(key=lambda x: x["von"]) 
                                while remaining > 0 and assets:
                                    biz = assets.pop(0)
                                    seized_biz.append(biz)
                                    biz_val = biz["von"]
                                    if biz_val >= remaining:
                                        refund = biz_val - remaining
                                        coin_data[player] = coin_data.get(player, 0) + refund
                                        remaining = 0
                                    else: remaining -= biz_val
                                assets_data[player]["businesses"] = assets
                                save_json_data(ASSETS_FILE, assets_data)
                                
                            loan_info["remaining"] = remaining
                            # Hoàn số tiền đã thu được về ví bot
                            collected = (loan_info["total"] - remaining) - (loan_info["total"] - loan_info.get("_prev_remaining", loan_info["total"]))
                            amount_collected = take_cash
                            # Tính tổng thu hồi từ vàng và cửa hàng
                            seized_biz_total = sum(b["von"] for b in seized_biz) - refund if seized_biz else 0
                            total_recovered = take_cash + seized_biz_total
                            if total_recovered > 0:
                                coin_data[BOT_NAME] = coin_data.get(BOT_NAME, BOT_DEFAULT_BALANCE) + total_recovered
                            save_json_data(COIN_FILE, coin_data)
                            
                            msg = f"🪓 Tẻn đã đi siết nợ hệ thống của {player}!\n"
                            if take_cash > 0: msg += f"💵 Tiền mặt: -{format_coin(take_cash)}.\n"
                            if seized_gold_msg: msg += seized_gold_msg
                            if seized_biz:
                                biz_names = ", ".join([b["ten"] for b in seized_biz])
                                msg += f"🏢 TỊCH THU TÀI SẢN: {biz_names}.\n"
                                if refund > 0: msg += f"⚖️ Thối lại tiền thừa: {format_coin(refund)}.\n"
                            
                            if remaining > 0: msg += f"📉 Vẫn còn nợ: {format_coin(remaining)}."
                            elif take_cash > 0 or seized_gold_msg or seized_biz: msg += f"✅ ĐÃ THANH TOÁN SẠCH NỢ!"
                            
                            if take_cash == 0 and not seized_gold_msg and not seized_biz:
                                msg = f"🪓 Tẻn đi siết nợ nhưng {player} rỗng túi và không có tài sản! Nợ: {format_coin(remaining)}."
                                
                            loan_info["last_seize_time"] = current_ts
                            save_json_data(LOAN_FILE, loan_data)
                            gui_tin_nhan_zalo(driver, msg)
                            
                            if loan_info["remaining"] <= 0:
                                del loan_data[player]; save_json_data(LOAN_FILE, loan_data)
                                credit_data[player] = max(0, credit_data.get(player, 0) - 10); save_json_data(CREDIT_FILE, credit_data)
                                gui_tin_nhan_zalo(driver, f"📉 {player} đã trả hết nợ hệ thống, nhưng bị TRỪ 10 điểm uy tín do không tự giác!")

                if time.time() - last_config_check_time > 30:
                    bot_config = load_bot_config(); last_config_check_time = time.time()

                target_time_morning = parse_time(bot_config.get("time_notication_morning", "07:00 AM"), 7, 0)
                if now.date() != last_morning_greet_date and now.hour == target_time_morning.hour and now.minute == target_time_morning.minute:
                    if gui_tin_nhan_zalo(driver, get_loi_chao_buoi_sang()): 
                        last_morning_greet_date = now.date()
                        try:
                            personal = load_json_data("personal_data.json", {})
                            today_str_1 = f"{now.day:02d}/{now.month:02d}"
                            today_str_2 = f"{now.day}/{now.month}"
                            for p_name, p_data in personal.items():
                                bd = p_data.get("birthday", "")
                                if bd and (bd.startswith(today_str_1) or bd.startswith(today_str_2)):
                                    bmsg = f"🎉 CHÚC MỪNG SINH NHẬT {p_name}! 🎂\nHệ thống chúc bạn một ngày sinh nhật thật bùng nổ, vui vẻ và luôn may mắn nha! 🎁🎈"
                                    gui_tin_nhan_zalo(driver, bmsg)
                        except Exception as e:
                            print(f"⚠️ [Birthday] Lỗi kiểm tra sinh nhật: {e}")
                        
                news_times = bot_config.get("time_send_news", ["09:00 AM"])
                if isinstance(news_times, str): news_times = [news_times]

                for time_str in news_times:
                    t_news = parse_time(time_str, 9, 0)
                    slot_key = f"{t_news.hour}_{t_news.minute}"
                    if now.date() != last_news_dates.get(slot_key) and now.hour == t_news.hour and now.minute == t_news.minute:
                        news_msg = fetch_vnexpress_top_story()
                        if news_msg and gui_tin_nhan_zalo(driver, news_msg): last_news_dates[slot_key] = now.date()

                # --- TỔNG KẾT DOANH THU 19:00 ---
                if now.date() != last_business_summary_date and now.hour == 19 and now.minute == 0:
                    daily_stats = get_daily_stats()
                    if daily_stats:
                        for player, stats in daily_stats.items():
                            if stats:
                                avt = user_avatars.get(player, "")
                                img_path = tao_anh_tong_ket_nha(player, stats, avt)
                                gui_anh_zalo(driver, img_path, f"📊 Báo cáo lợi nhuận các cơ sở kinh doanh trong ngày của {player}")
                        reset_daily_stats()  # Xoá qua RAM + flush async, không ghi DB trực tiếp
                    last_business_summary_date = now.date()

            # ==============================================================================
            # 👁️ GEAR 3: QUÉT MẮT ZALO TÌM TIN NHẮN MỚI (CƠ CHẾ CŨ - ỔN ĐỊNH 100%)
            # ==============================================================================
            try:
                message_elements = driver.find_elements(By.CSS_SELECTOR, "div[id^='bb_msg_id_']")
                if not message_elements: 
                    time.sleep(0.5)
                    continue

                new_messages = []
                if last_processed_msg_id is None: 
                    new_messages = [message_elements[-1]]
                else:
                    idx = -1
                    for i, m in enumerate(message_elements):
                        if m.get_attribute("id") == last_processed_msg_id: 
                            idx = i
                            break
                    if idx != -1 and idx < len(message_elements) - 1: 
                        new_messages = message_elements[idx+1:]
                    elif idx == -1: # Xử lý trường hợp trôi tin nhắn
                        new_messages = [message_elements[-1]]

                # Nếu không có tin nhắn mới thì cho bot ngủ nửa giây để VPS không bị quá tải CPU
                if not new_messages:
                    time.sleep(0.5)
                    continue
                    
            except Exception as e:
                # Nếu web Zalo bị giật lag nháy mắt, bot sẽ tự bỏ qua và thử lại ở giây tiếp theo
                time.sleep(1)
                continue

            for msg_obj in new_messages:
                last_processed_msg_id = msg_obj.get_attribute("id")
                if len(msg_obj.find_elements(By.CSS_SELECTOR, "[data-id*='Sticker'], [data-component='sticker']")) > 0: continue 

                    # 🧠 FIX LỖI NHẬN NHẦM NGƯỜI: Chuyển khối quét Tên ra ngoài cùng!
                # Bất kể là gửi text hay gửi ảnh, Bot đều phải "nhìn" xem ai đang gửi để cập nhật last_other_sender
                sender_name = "Bạn"
                try:
                    if msg_obj.find_elements(By.CSS_SELECTOR, ".message-wrapper--me"): sender_name = "Tẻn"
                    else:
                        sender_name = last_other_sender 
                        name_elements = msg_obj.find_element(By.XPATH, "./ancestor::div[contains(@class, 'chat-item')]").find_elements(By.CSS_SELECTOR, ".message-sender-name-content")
                        if name_elements:
                            extracted_name = name_elements[0].text.replace('\xa0', ' ').strip()
                            if extracted_name: 
                                sender_name = extracted_name
                                last_other_sender = sender_name
                except Exception as e:
                    print(f"⚠️ [Scan] Lỗi lấy tên người gửi: {e}")

                if sender_name != "Tẻn":
                    # --- ĐOẠN QUÉT VÀ LƯU AVATAR ---
                    try:
                        chat_item = msg_obj.find_element(By.XPATH, "./ancestor::div[contains(@class, 'chat-item')]")
                        avt_imgs = chat_item.find_elements(By.CSS_SELECTOR, ".zavatar-container img")
                        if avt_imgs:
                            avt_src = avt_imgs[0].get_attribute("src")
                            if avt_src and avt_src.startswith("http") and "default" not in avt_src:
                                if user_avatars.get(sender_name) != avt_src:
                                    user_avatars[sender_name] = avt_src
                                    save_json_data(AVATAR_FILE, user_avatars)
                                    preload_avatar_async(avt_src)
                    except Exception as e:
                        print(f"⚠️ [Scan] Lỗi quét avatar {sender_name}: {e}")
                    # -------------------------------

                    # 📸 FIX: Mở rộng điều kiện - Có Text HOẶC Có Ảnh thì đều xử lý!
                    has_text = len(msg_obj.find_elements(By.CSS_SELECTOR, "div[data-component='message-text-content']")) > 0
                    has_img = len(msg_obj.find_elements(By.CSS_SELECTOR, "img[src^='blob:']")) > 0

                    if has_text or has_img:
                        current_msg_text = ""
                        mentioned_names = [] 
                        base64_img = None 
                        
                        try:
                            # 1. LẤY TEXT
                            text_elem = msg_obj.find_elements(By.CSS_SELECTOR, "div[data-component='message-text-content']")
                            if text_elem:
                                current_msg_text = text_elem[0].text.strip()
                                
                            # 2. KHÔNG DÙNG BASE64 IMAGE BASE64 KHỈ AI ĐÃ BỊ LOẠI BỎ
                            base64_img = None
                        except Exception as e:
                            print(f"⚠️ [Scan] Lỗi đọc text tin nhắn: {e}")

                        # 3. TÌM NGƯỜI BỊ TAG (MENTION)
                        try:
                            mention_elems = msg_obj.find_elements(By.CSS_SELECTOR, ".mention-name")
                            for m in mention_elems:
                                m_text = m.text.replace('@', '').replace('\xa0', ' ').strip()
                                if m_text: mentioned_names.append(m_text)
                        except Exception as e:
                            print(f"⚠️ [Scan] Lỗi quét mention: {e}")

                        # 4. CỘNG TIỀN VÀ XỬ LÝ LỆNH
                        if not current_msg_text.startswith(PREFIX):
                            coin_data[sender_name] = coin_data.get(sender_name, 0) + 5
                            user_msg_counts[sender_name] = user_msg_counts.get(sender_name, 0) + 1
                            
                        reply_data = xu_ly_lenh(sender_name, current_msg_text, mentioned_names, user_msg_counts, tarot_data, coin_data, loan_data, credit_data, pending_loans, jobs_data, player_streaks, altp_games, business_config, assets_data, p2p_data, pending_p2p, xidach_games, gold_data, altp_winners_data, profile_data, user_avatars, caro_games, pending_caro, None)
                        
                        if reply_data: 
                            if isinstance(reply_data, dict) and reply_data.get("type") == "image":
                                gui_anh_zalo(driver, reply_data["path"], reply_data.get("caption", ""))
                            elif isinstance(reply_data, dict) and reply_data.get("type") == "video":
                                vpath = reply_data["path"]
                                gui_video_zalo(driver, vpath, reply_data.get("caption", ""))
                                try:
                                    if os.path.exists(vpath):
                                        os.remove(vpath)
                                        print(f"🧹 Đã xóa video tạm: {vpath}")
                                except Exception as ve:
                                    print(f"⚠️ Lỗi xóa video tạm: {ve}")
                            elif isinstance(reply_data, list):
                                for t in reply_data:
                                    if isinstance(t, dict) and t.get("type") == "image":
                                        gui_anh_zalo(driver, t["path"], t.get("caption", ""))
                                    elif isinstance(t, dict) and t.get("type") == "video":
                                        vpath = t["path"]
                                        gui_video_zalo(driver, vpath, t.get("caption", ""))
                                        try:
                                            if os.path.exists(vpath):
                                                os.remove(vpath)
                                        except Exception:
                                            pass
                                    else:
                                        gui_tin_nhan_zalo(driver, t)
                                    time.sleep(0.8)
                            else:
                                gui_tin_nhan_zalo(driver, reply_data)
        # Bắt sự kiện sếp bấm Ctrl + C để thoát cho mượt
        except KeyboardInterrupt:
            print("\n🛑 Đã nhận lệnh dừng từ sếp (Ctrl+C)! Đang tắt Tẻn và dọn dẹp trình duyệt...")
            try:
                driver.quit()
            except Exception:
                pass  # Driver đã chết rồi — bỏ qua
            break

        except Exception as e:
            error_msg = str(e)
            if "Connection refused" in error_msg or "Max retries exceeded" in error_msg or "not reachable" in error_msg or "session not created" in error_msg or "chrome not reachable" in error_msg:
                print("\n🔄 Chrome bị crash! Đang tự khởi động lại sau 10 giây...")
                try:
                    driver.quit()
                except Exception:
                    pass  # Driver đã chết rồi
                time.sleep(10)
                try:
                    driver = init_browser()
                    last_processed_msg_id = None  # Reset để tránh xử lý lại tin cũ
                    print("✅ Chrome đã khởi động lại thành công!")
                    try:
                        search_box = driver.find_element(By.ID, "contact-search-input")
                        search_box.clear()
                        search_box.send_keys(TEN_NHOM_CHAT)
                        time.sleep(2)
                        search_box.send_keys(Keys.ENTER)
                    except Exception as se:
                        print(f"⚠️ [Restart] Không tìm được search box: {se}")
                except Exception as restart_err:
                    print(f"❌ Không thể restart Chrome: {restart_err}. Thoát hẳn.")
                    break
                continue

            print(f"❌ LỖI VÒNG LẶP: {e}")
            traceback.print_exc()
            time.sleep(1)

if __name__ == "__main__":
    main()