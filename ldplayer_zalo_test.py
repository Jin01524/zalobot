import time
import os
import re
import uuid
import requests
import msvcrt
import uiautomator2 as u2

# Cấu hình địa chỉ ADB LDPlayer (Mặc định LDPlayer 9 là 127.0.0.1:5555 hoặc 127.0.0.1:62001)
LDPLAYER_ADB = "127.0.0.1:5555" 
ZALO_PACKAGE = "com.zing.zalo"
TARGET_GROUP_NAME = "Nà ná na na"  # Tên nhóm chat mẫu
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# Danh sách bạn bè kiểm tra Story FB theo yêu cầu
STORY_FRIENDS = {
    "bình": {"name": "Vo Bình", "url": "https://www.facebook.com/Jin01050", "status": "ok"},
    "binh": {"name": "Vo Bình", "url": "https://www.facebook.com/Jin01050", "status": "ok"},
    "huy": {"name": "Huy Nguyễn", "url": "https://www.facebook.com/huy.nguyen.562977", "status": "ok"},
    "vit": {"name": "Pham Davit", "url": "https://www.facebook.com/pham.davit.37", "status": "ok"},
    "tâm": {"name": "Nguyễn Trương Minh Tâm", "url": "https://www.facebook.com/nguyen.truong.minh.tam.2024", "status": "ok"},
    "tam": {"name": "Nguyễn Trương Minh Tâm", "url": "https://www.facebook.com/nguyen.truong.minh.tam.2024", "status": "ok"},
    "nhung": {"name": "Nhung Trần", "url": "https://www.facebook.com/nhung.tran.478695", "status": "ok"},
    "mai": {"name": "Huỳnh Phương Mai", "url": "https://www.facebook.com/huynh.phuong.mai.41724", "status": "ok"},
    "phương": {"name": "Quảng Thị Minh Phương", "url": "https://www.facebook.com/quang.thi.minh.phuong.2025", "status": "ok"},
    "phuong": {"name": "Quảng Thị Minh Phương", "url": "https://www.facebook.com/quang.thi.minh.phuong.2025", "status": "ok"},
    "tuân": {"name": "Tuân", "url": "", "status": "not_friend"},
    "tuan": {"name": "Tuân", "url": "", "status": "not_friend"}
}

def init_ldplayer():
    print(f"🔌 Đang kết nối tới LDPlayer tại {LDPLAYER_ADB}...")
    try:
        d = u2.connect(LDPLAYER_ADB)
        print(f"✅ Đã kết nối thành công thiết bị: {d.info.get('productName', 'Android Device')}")
        return d
    except Exception as e:
        print(f"❌ Không thể kết nối ADB LDPlayer: {e}")
        print("💡 Gợi ý: Hãy kiểm tra xem LDPlayer đã bật tính năng ADB Debugging chưa.")
        return None

def normalize_video_url(url):
    """
    Chuẩn hóa URL Facebook/TikTok/YouTube trước khi đưa vào downloader.
    Tự động trích xuất ID số chuẩn của FB Reel/Watch/Video (ví dụ: 1498614348705271) ngay cả khi bị dính chuỗi lượt xem '49K'.
    """
    url_str = str(url).strip().strip("<>").strip()
    if any(domain in url_str.lower() for domain in ["facebook.com", "fb.watch", "fb.gg"]):
        # 1. Thử trích xuất theo đường dẫn dạng facebook.com/reel/1498614348705271 hoặc watch/?v=1498614348705271
        match = re.search(r'facebook\.com/(?:reel|watch|videos|share/[rv])/(\d{10,16})', url_str)
        if match:
            return f"https://www.facebook.com/{match.group(1)}"
            
        # 2. Thử trích xuất ID số 10-16 chữ số bất kỳ
        match_id = re.search(r'(\d{10,16})', url_str)
        if match_id:
            return f"https://www.facebook.com/{match_id.group(1)}"
            
        try:
            r = requests.head(url_str, headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}, allow_redirects=True, timeout=5)
            final_url = r.url
            match_final = re.search(r'(\d{10,16})', final_url)
            if match_final:
                return f"https://www.facebook.com/{match_final.group(1)}"
            return final_url
        except Exception:
            pass
    return url_str

def download_video_web(target_url, output_dir):
    """Tải video đa nền tảng bằng yt-dlp trực tiếp mà không bắt buộc ffmpeg."""
    target_url = normalize_video_url(target_url)
    try:
        import yt_dlp
        unique_id = str(uuid.uuid4())[:8]
        out_template = os.path.join(output_dir, f"temp_video_{unique_id}.%(ext)s")
        ydl_opts = {
            # Ưu tiên mp4 dưới 25MB để Zalo nhận được, fallback best nếu không có
            'format': 'best[ext=mp4][filesize<25M]/best[ext=mp4][filesize<50M]/best[ext=mp4]/best',
            'outtmpl': out_template,
            'quiet': True,
            'no_warnings': True,
            'max_filesize': 50 * 1024 * 1024, # 50MB
            'user_agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36',
        }
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(target_url, download=True)
            filename = ydl.prepare_filename(info)
            if os.path.exists(filename) and os.path.getsize(filename) > 50000:
                if not filename.lower().endswith(".mp4"):
                    new_mp4 = os.path.splitext(filename)[0] + ".mp4"
                    try:
                        os.rename(filename, new_mp4)
                        filename = new_mp4
                    except Exception:
                        pass
                print(f"✅ [yt-dlp] Tải video thành công: {filename}")
                return filename
    except Exception as e:
        print(f"⚠️ [yt-dlp] Lỗi tải video: {e}")
    return None

def is_in_chat_room(d):
    """Kiểm tra xem hiện tại có phải đang ở trong màn hình phòng chat hay không (Dựa trên XML Dump chuẩn)."""
    return (
        d(resourceId="com.zing.zalo:id/chatinput_text").exists or 
        d(resourceId="com.zing.zalo:id/chatlinelist").exists or 
        d(resourceId="com.zing.zalo:id/new_chat_input_btn_show_gallery").exists
    )

def start_zalo_and_open_chat(d, group_name):
    print("🚀 Đang khởi động ứng dụng Zalo...")
    d.app_start(ZALO_PACKAGE)
    time.sleep(3)

    # 1. Nếu đã ở trong phòng chat sẵn
    if is_in_chat_room(d):
        print(f"✅ Đã ở trong phòng chat sẵn.")
        return True

    # Nếu đang bị văng vào màn hình phụ/tìm kiếm, bấm Trở về để quay lại màn hình danh sách chat
    for _ in range(2):
        if not is_in_chat_room(d) and d(resourceId="com.zing.zalo:id/actionbar_btn_leading").exists:
            d(resourceId="com.zing.zalo:id/actionbar_btn_leading").click()
            time.sleep(1)

    if is_in_chat_room(d):
        print(f"✅ Đã ở trong phòng chat sẵn.")
        return True

    # 2. Thử click trực tiếp vào nhóm nếu đã hiển thị ngay màn hình danh sách tin nhắn
    group_item = d.xpath(f"//*[contains(@text, '{group_name}')]")
    if group_item.exists and not d(resourceId="com.zing.zalo:id/search_src_text").exists:
        matches = group_item.all()
        if matches:
            matches[0].click()
            time.sleep(2)
            if is_in_chat_room(d):
                print(f"✅ Đã chọn phòng chat từ danh sách: '{group_name}'")
                return True

    # 3. Tìm ô Tìm kiếm trên giao diện Zalo Android
    print(f"🔍 Đang tìm kiếm nhóm chat: '{group_name}'...")
    search_bar = None
    search_selectors = [
        d(resourceId="com.zing.zalo:id/mSearchLayout"),
        d(resourceId="com.zing.zalo:id/btn_search"),
        d(resourceId="com.zing.zalo:id/input_search"),
        d(resourceId="com.zing.zalo:id/search_icon"),
        d(resourceId="com.zing.zalo:id/main_tab_search"),
        d(text="Tìm kiếm"),
        d(textContains="Tìm kiếm"),
        d(description="Tìm kiếm")
    ]
    for s in search_selectors:
        if s.exists:
            search_bar = s
            break

    if search_bar:
        try:
            search_bar.click()
            time.sleep(1.5)
            
            # Nhập tên nhóm vào ô EditText của Tìm kiếm
            search_input = (
                d(resourceId="com.zing.zalo:id/search_src_text") or 
                d(resourceId="com.zing.zalo:id/input_search") or
                d(className="android.widget.EditText")
            )
            if search_input.exists:
                search_input.set_text(group_name)
                time.sleep(1.0)
                try:
                    d.press("enter")
                except Exception:
                    pass

                print(f"⏳ Đang chờ và nhấp kết quả tìm kiếm cho '{group_name}'...")
                time.sleep(2.0)
                
                # Dùng XPath để lấy tọa độ dòng kết quả và nhấp trực tiếp
                xpath_item = d.xpath(f"//*[contains(@text, '{group_name}')]")
                if xpath_item.wait(timeout=6.0):
                    matches = xpath_item.all()
                    for m in matches:
                        # Bỏ qua ô nhập từ khóa tìm kiếm (EditText)
                        if m.info.get("className") != "android.widget.EditText":
                            m.click()
                            print(f"👉 Đã nhấp vào dòng kết quả nhóm: '{group_name}'")
                            time.sleep(3.0)
                            if is_in_chat_room(d) or not d(resourceId="com.zing.zalo:id/search_src_text").exists:
                                print(f"✅ Đã mở phòng chat thành công: '{group_name}'")
                                return True
                            break
        except Exception as e:
            print(f"⚠️ Lỗi trong quá trình tìm kiếm: {e}")

    print(f"❌ Không mở được phòng chat: '{group_name}'")
    return False

def send_zalo_message(d, text_msg):
    """Gửi tin nhắn văn bản (CHỈ GỬI KHI ĐÃ Ở TRONG PHÒNG CHAT)."""
    try:
        input_box = None
        selectors = [
            d(resourceId="com.zing.zalo:id/chatinput_text"),
            d(resourceId="com.zing.zalo:id/chat_input_text"),
            d(resourceId="com.zing.zalo:id/input_chat"),
            d(className="android.widget.EditText")
        ]
        for sel in selectors:
            if sel.exists:
                input_box = sel
                break

        if input_box:
            input_box.set_text(text_msg)
            time.sleep(0.5)
            
            send_btn = None
            send_selectors = [
                d(resourceId="com.zing.zalo:id/btn_send"),
                d(resourceId="com.zing.zalo:id/chat_btn_send"),
                d(resourceId="com.zing.zalo:id/btn_chat_send"),
                d(description="Gửi")
            ]
            for s_btn in send_selectors:
                if s_btn.exists:
                    send_btn = s_btn
                    break

            if send_btn:
                send_btn.click()
            else:
                d.press("enter")

            print(f"📤 Đã gửi tin nhắn: {text_msg}")
            return True
        else:
            print("⚠️ Không tìm thấy ô nhập tin nhắn trong phòng chat!")
    except Exception as e:
        print(f"⚠️ Lỗi gửi tin nhắn: {e}")
    return False

ZALO_MAX_VIDEO_MB = 25  # Giới hạn kích thước video Zalo có thể gửi được (MB)

def send_zalo_video_android(d, video_path):
    """
    Gửi Video MXH trực tiếp vào nhóm chat Zalo Android qua LDPlayer:
    1. Kiểm tra kích thước file (>25MB sẽ cảnh báo nhưng vẫn thử gửi).
    2. Push file .mp4 vào Android, gọi MediaScanner quét 2 lần để đảm bảo Zalo thấy file mới.
    3. Mở Thư viện, chọn video mới nhất, bấm Gửi, kiểm tra lỗi 'Không gửi được' và retry.
    """
    try:
        abs_path = os.path.abspath(video_path)
        if not os.path.exists(abs_path):
            print(f"❌ File video không tồn tại: {abs_path}")
            return False

        # Kiểm tra kích thước file
        file_size_mb = os.path.getsize(abs_path) / (1024 * 1024)
        print(f"📦 Kích thước file video: {file_size_mb:.1f} MB")
        if file_size_mb > ZALO_MAX_VIDEO_MB:
            print(f"⚠️ Video {file_size_mb:.1f}MB vượt quá {ZALO_MAX_VIDEO_MB}MB! Zalo có thể không gửi được.")
            send_zalo_message(d, f"⚠️ Video quá nặng ({file_size_mb:.0f}MB), Zalo chỉ hỗ trợ tối đa {ZALO_MAX_VIDEO_MB}MB. Tẻn thử gửi nhé...")

        if not abs_path.lower().endswith(".mp4"):
            new_mp4 = os.path.splitext(abs_path)[0] + ".mp4"
            try:
                os.rename(abs_path, new_mp4)
                abs_path = new_mp4
            except Exception:
                pass

        remote_android_path = "/sdcard/DCIM/Camera/temp_bot_video.mp4"

        # Xóa file cũ trước khi đẩy file mới để tránh nhầm lẫn
        d.shell(f"rm -f {remote_android_path}")
        time.sleep(0.5)
        
        print("📲 Đang đẩy video vào thư viện Android LDPlayer...")
        d.push(abs_path, remote_android_path)
        time.sleep(1)

        # Broadcast MediaScanner 2 lần để đảm bảo Zalo cập nhật ngay file mới
        d.shell(f"am broadcast -a android.intent.action.MEDIA_SCANNER_SCAN_FILE -d file://{remote_android_path}")
        time.sleep(2)  # Tăng thời gian chờ để Thư viện Zalo index xong
        d.shell(f"am broadcast -a android.intent.action.MEDIA_SCANNER_SCAN_FILE -d file://{remote_android_path}")
        time.sleep(1.5)

        for attempt in range(2):  # Thử gửi tối đa 2 lần
            if attempt > 0:
                print(f"🔄 Thử lại lần {attempt + 1} do lỗi gửi video...")
                time.sleep(2)

            # Click icon Thư viện Ảnh/Video trên thanh công cụ chat Zalo
            print("🖼️ Đang mở Thư viện media Zalo...")
            photo_btn = d(resourceId="com.zing.zalo:id/new_chat_input_btn_show_gallery")
            if photo_btn.exists:
                photo_btn.click()
                time.sleep(2.5)
            else:
                d.click(850, 1110)
                time.sleep(2.5)

            # Chọn video đầu tiên (ô mới nhất)
            print("🎬 Đang chọn video mới nhất...")
            video_item = None
            video_selectors = [
                d.xpath("//*[@resource-id='com.zing.zalo:id/media_picker_layout']//android.widget.FrameLayout[2]"),
                d(resourceId="com.zing.zalo:id/iv_thumb")
            ]
            for v_sel in video_selectors:
                if v_sel.exists:
                    video_item = v_sel
                    break

            if video_item:
                video_item.click()
                time.sleep(1)
            else:
                d.click(450, 1309)
                time.sleep(1)

            # Bật chế độ HD nếu có
            hd_option = d(resourceId="com.zing.zalo:id/btn_hd") or d(text="HD")
            if hd_option.exists:
                try:
                    hd_option.click()
                    time.sleep(0.5)
                except Exception:
                    pass

            # Nhấp nút Gửi
            send_btn = None
            for s_sel in [
                d(resourceId="com.zing.zalo:id/btn_send"),
                d(resourceId="com.zing.zalo:id/chat_btn_send"),
                d(resourceId="com.zing.zalo:id/btn_chat_send"),
                d(text="Gửi"),
                d(description="Gửi")
            ]:
                if s_sel.exists:
                    send_btn = s_sel
                    break

            if send_btn:
                send_btn.click()
            else:
                d.click(820, 1550)

            time.sleep(4)

            # Kiểm tra lỗi "Không gửi được" xuất hiện trên màn hình
            if d(textContains="Không gửi được").exists or d(textContains="Gửi thất bại").exists:
                print(f"⚠️ Phát hiện lỗi gửi video (lần {attempt + 1})! Sẽ thử lại...")
                # Bấm Back để quay về phòng chat trước khi thử lại
                d.press("back")
                time.sleep(1)
                if not is_in_chat_room(d):
                    start_zalo_and_open_chat(d, TARGET_GROUP_NAME)
                continue  # Thử lại

            print("🚀 Đã phát video thành công vào nhóm Zalo Android!")
            cleanup_temp_videos(d, abs_path)
            return True

        # Sau 2 lần thử vẫn không gửi được
        print("❌ Không thể gửi video sau 2 lần thử. Video quá nặng hoặc định dạng không hỗ trợ.")
        send_zalo_message(d, "❌ Video tải về quá nặng, Zalo không gửi được. Sếp thử link khác nhé!")
        cleanup_temp_videos(d, abs_path)
        return False
    except Exception as e:
        print(f"❌ Lỗi gửi video Android: {e}")
    return False

def cleanup_temp_videos(d, local_video_path=None):
    """Xóa sạch hoàn toàn các file video/ảnh tạm cả trên máy tính (PC) lẫn bộ nhớ giả lập Android (LDPlayer)."""
    if local_video_path and os.path.exists(local_video_path):
        try:
            os.remove(local_video_path)
            print(f"🗑️ Đã xóa file tạm trên PC: {os.path.basename(local_video_path)}")
        except Exception:
            pass

    try:
        for f in os.listdir(BASE_DIR):
            if (f.startswith("temp_video_") or f.startswith("temp_story_")) and (f.endswith(".mp4") or f.endswith(".png")):
                try:
                    os.remove(os.path.join(BASE_DIR, f))
                except Exception:
                    pass
    except Exception:
        pass

    try:
        remote_path = "/sdcard/DCIM/Camera/temp_bot_video.mp4"
        d.shell(f"rm -f {remote_path}")
        d.shell("rm -f /sdcard/DCIM/Camera/temp_bot_video*.mp4")
        d.shell("rm -f /sdcard/DCIM/Camera/temp_story_screenshot*.png")
        d.shell("rm -f /sdcard/Download/temp_bot_video*.mp4")
        d.shell(f"am broadcast -a android.intent.action.MEDIA_SCANNER_SCAN_FILE -d file://{remote_path}")
        print("🧹 Đã dọn dẹp và làm sạch bộ nhớ Thư viện trên LDPlayer!")
    except Exception as e:
        print(f"⚠️ Lỗi dọn dẹp Android: {e}")

def is_timestamp_or_status(s):
    """Kiểm tra xem chuỗi có phải là mốc thời gian (vd: 22:33, 07:15), tên nhóm header hoặc trạng thái giao diện không."""
    s_clean = s.strip()
    if re.match(r'^\d{1,2}:\d{2}$', s_clean):
        return True
    if s_clean in [TARGET_GROUP_NAME, "Nà ná na na", "Search games", "Không có mục gần đây nào", "Đã nhận", "Đã xem", "Đã gửi", "Của tôi", "Khám phá", "Liên hệ", "Zalo", "Tin nhắn", "Gửi", "Xem cập nhật trước", "Xem"]:
        return True
    if "không phản hồi" in s_clean or "không phản hồi" in s_clean.lower():
        return True
    return False

def extract_latest_chat_record(d):
    """
    Trích xuất chi tiết tin nhắn mới nhất từ danh sách chatlinelist bao gồm:
    - sender: Tên người gửi (Ví dụ: 'Võ Ngọc Bình', 'Tâm'...)
    - timestamp: Mốc thời gian gửi (Ví dụ: '00:13', '00:19')
    - content: Nội dung tin nhắn chính xác
    - signature: Khóa vân tay đối chiếu duy nhất (sender|timestamp|content)
    """
    try:
        items = d.xpath("//*[@resource-id='com.zing.zalo:id/chatlinelist']/*").all()
        if items:
            for item in reversed(items):
                full_text = item.text or ""
                lines = [l.strip() for l in full_text.splitlines() if l.strip()]
                if not lines:
                    continue

                timestamp = ""
                sender = ""
                content = ""

                # 1. Tìm mốc thời gian (vd: 00:13, 23:45)
                for t in lines:
                    if re.match(r'^\d{1,2}:\d{2}$', t):
                        timestamp = t
                        break

                # 2. Tách người gửi và nội dung
                valid_lines = [t for t in lines if not re.match(r'^\d{1,2}:\d{2}$', t) and not is_timestamp_or_status(t)]
                if valid_lines:
                    full_str = " ".join(valid_lines)
                    if "Tẻn Android Bot" in full_str or "kết nối trực tiếp thành công" in full_str or "Tẻn đang tạo Bảng Bình Chọn" in full_str:
                        continue

                    # Ưu tiên tìm dòng chứa lệnh hoặc thông báo bình chọn
                    cmd_line = ""
                    for l in valid_lines:
                        if l.startswith("/") or "http" in l or "www." in l or "bình chọn" in l.lower() or "tham gia" in l.lower() or "chọn" in l.lower():
                            cmd_line = l
                            break

                    if cmd_line:
                        content = cmd_line
                    else:
                        content = valid_lines[0]

                    if len(valid_lines) >= 2 and not valid_lines[0].startswith('/'):
                        sender = valid_lines[0]

                if content:
                    signature = f"{sender}|{timestamp}|{content}"
                    return {
                        "sender": sender,
                        "timestamp": timestamp,
                        "content": content,
                        "signature": signature
                    }
    except Exception as e:
        print(f"⚠️ Lỗi đọc chat record: {e}")
    return None

def exit_to_android_home(d):
    """Tắt sạch toàn bộ ứng dụng Zalo chạy ngầm và quay về màn hình chính Android LDPlayer."""
    print("\n🧹 Đang dọn dẹp và tắt sạch ứng dụng Zalo...")
    try:
        if d:
            d.app_stop(ZALO_PACKAGE)
            d.shell(f"am force-stop {ZALO_PACKAGE}")
            time.sleep(0.5)
            d.press("home")
            time.sleep(1)
    except Exception as e:
        print(f"⚠️ Lỗi tắt ứng dụng ngầm: {e}")
    print("🛑 Bot đã tắt sạch ứng dụng ngầm và quay về màn hình chính an toàn!")

processed_records = set()

def is_already_processed(record):
    """Kiểm tra xem bộ (người gửi + thời gian + nội dung) này đã được xử lý trước đó hay chưa."""
    if not record or not record.get("signature"):
        return True
    return record["signature"] in processed_records

def mark_as_processed(record):
    """Lưu vết bộ (người gửi + thời gian + nội dung) vào lịch sử để chống lặp lại hành động."""
    if not record or not record.get("signature"):
        return
    sig = record["signature"]
    processed_records.add(sig)
    print(f"📝 [Record Saved] Người gửi: '{record['sender']}' | Thời gian: '{record['timestamp']}' | Nội dung: '{record['content']}'")
    if len(processed_records) > 100:
        processed_records.clear()

def main():
    d = init_ldplayer()
    if not d:
        return

    # Mở Zalo & Nhóm Chat
    if start_zalo_and_open_chat(d, TARGET_GROUP_NAME):
        send_zalo_message(d, "🤖 Tẻn Android Bot (LDPlayer) đã kết nối trực tiếp thành công!")
        
        print("👁️ Bắt đầu vòng lặp lắng nghe tin nhắn Zalo Android... (Gõ 'stop' + Enter hoặc Ctrl+C để quay về màn hình chính Android)")
        cmd_buffer = ""
        try:
            while True:
                # Kiểm tra phím gõ từ CMD (Nhận lệnh 'stop' + Enter)
                if msvcrt.kbhit():
                    ch = msvcrt.getwch()
                    if ch in ['\r', '\n']:
                        typed_cmd = cmd_buffer.strip().lower()
                        cmd_buffer = ""
                        if typed_cmd == "stop":
                            print("\n🛑 Nhận lệnh 'stop' từ màn hình CMD!")
                            exit_to_android_home(d)
                            return
                    elif ch in ['\b', '\x08']:
                        cmd_buffer = cmd_buffer[:-1]
                    else:
                        cmd_buffer += ch

                # Nếu bị văng ra khỏi phòng chat (do văng app hoặc bấm nhầm nút), tự động mở lại phòng chat
                if not is_in_chat_room(d):
                    print("🔄 Phát hiện bị thoát phòng chat! Đang tự động mở lại phòng chat...")
                    start_zalo_and_open_chat(d, TARGET_GROUP_NAME)
                    time.sleep(2)
                    continue

                record = extract_latest_chat_record(d)
                if record and not is_already_processed(record):
                    mark_as_processed(record)
                    sender = record["sender"]
                    msg_time = record["timestamp"]
                    msg_text = record["content"]
                    
                    print(f"📩 [Scan Result] Người gửi: '{sender}' | Thời gian: '{msg_time}' | Nội dung: '{msg_text}'")
                    
                    if msg_text.startswith("/ping"):
                        send_zalo_message(d, "🏓 Pong! Bot LDPlayer đang phản hồi cực nhanh!")
                    elif msg_text.startswith("/menu"):
                        send_zalo_message(d, "📜 [TẺN ANDROID BOT]\n- /ping\n- /menu\n- /video [link_fb_tt_yt]\n- Gõ 'stop' ở CMD để tắt ứng dụng ngầm & về Home")
                    elif msg_text.startswith("/video") or msg_text.startswith("/v ") or any(domain in msg_text for domain in ["facebook.com", "fb.watch", "tiktok.com", "youtube.com", "youtu.be"]):
                        url_match = re.search(r'((?:https?://|www\.)[^\s]+)', msg_text)
                        if url_match:
                            target_url = url_match.group(1)
                            if target_url.startswith("www."):
                                target_url = "https://" + target_url
                            print(f"🎬 [Video Handler] Đang xử lý tải URL: {target_url}")
                            send_zalo_message(d, "⏳ Tẻn đang tải video MXH về nhóm, sếp chờ xíu nhé...")
                            v_file = download_video_web(target_url, BASE_DIR)
                            if v_file:
                                send_zalo_video_android(d, v_file)
                                cleanup_temp_videos(d, v_file)
                            else:
                                send_zalo_message(d, "❌ Không thể tải video từ liên kết này!")

                time.sleep(1)
        except KeyboardInterrupt:
            exit_to_android_home(d)

if __name__ == "__main__":
    main()
