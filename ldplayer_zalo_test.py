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
            'format': 'best[ext=mp4]/bestvideo[ext=mp4]+bestaudio[ext=m4a]/best',
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

def send_zalo_video_android(d, video_path):
    """
    Gửi Video MXH trực tiếp vào nhóm chat Zalo Android qua LDPlayer (Cấu hình từ XML Dump):
    1. Push file .mp4 từ máy tính vào thẻ nhớ Android (/sdcard/DCIM/Camera/temp_bot_video.mp4).
    2. Gọi MediaScanner để Zalo Android cập nhật video mới vào Thư viện.
    3. Mở Bộ chọn Thư viện Zalo, chọn video mới nhất (Bounds [301,1160][599,1458]) và bấm Gửi HD.
    """
    try:
        abs_path = os.path.abspath(video_path)
        if not os.path.exists(abs_path):
            print(f"❌ File video không tồn tại: {abs_path}")
            return False

        if not abs_path.lower().endswith(".mp4"):
            new_mp4 = os.path.splitext(abs_path)[0] + ".mp4"
            try:
                os.rename(abs_path, new_mp4)
                abs_path = new_mp4
            except Exception:
                pass

        remote_android_path = "/sdcard/DCIM/Camera/temp_bot_video.mp4"
        
        print("📲 Đang đẩy video vào thư viện Android LDPlayer...")
        d.push(abs_path, remote_android_path)
        time.sleep(1)

        # Broadcast MediaScanner để Zalo Android cập nhật ngay video mới
        d.shell(f"am broadcast -a android.intent.action.MEDIA_SCANNER_SCAN_FILE -d file://{remote_android_path}")
        time.sleep(1.5)

        # Click icon Thư viện Ảnh/Video trên thanh công cụ chat Zalo
        print("🖼️ Đang mở Thư viện media Zalo...")
        photo_btn = d(resourceId="com.zing.zalo:id/new_chat_input_btn_show_gallery")
        if photo_btn.exists:
            photo_btn.click()
            time.sleep(2)
        else:
            d.click(850, 1110)
            time.sleep(2)

        # Chọn video đầu tiên (Ô thứ 2 bên cạnh ô Chụp ảnh - Tọa độ chuẩn từ XML Dump [301,1160][599,1458])
        print("🎬 Đang chọn video mới nhất...")
        video_item = None
        video_selectors = [
            d.xpath("//*[contains(@text, ':')]"),
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
            # Click tâm ô Video thứ 2 (X=450, Y=1309)
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
        send_selectors = [
            d(resourceId="com.zing.zalo:id/btn_send"),
            d(resourceId="com.zing.zalo:id/chat_btn_send"),
            d(resourceId="com.zing.zalo:id/btn_chat_send"),
            d(text="Gửi"),
            d(textContains="Gửi"),
            d(description="Gửi")
        ]
        for s_btn in send_selectors:
            if s_btn.exists:
                send_btn = s_btn
                break

        if send_btn:
            send_btn.click()
        else:
            # Click góc dưới bên phải nút Gửi (X=820, Y=1550)
            d.click(820, 1550)

        print("🚀 Đã phát video thành công vào nhóm Zalo Android!")
        time.sleep(3)

        # Xóa và làm sạch file tạm trên cả Android LDPlayer lẫn máy tính (PC)
        cleanup_temp_videos(d, abs_path)
        return True
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
                    else:
                        if " tham gia cuộc bình chọn" in content:
                            sender = content.split(" tham gia cuộc bình chọn")[0].strip()
                        elif " bình chọn" in content:
                            sender = content.split(" bình chọn")[0].strip()

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

active_poll_initiator = ""

def create_story_poll_zalo(d, initiator_name=""):
    """
    Tự động tạo Bảng Bình Chọn Story FB trong nhóm Zalo khi gõ lệnh /storyfb:
    - Cấu hình: TẮT 'Chọn nhiều phương án' & TẮT 'Có thể thêm phương án'.
    - Ghi nhớ người khởi tạo lệnh để phân quyền bình chọn.
    """
    global active_poll_initiator
    if initiator_name:
        active_poll_initiator = initiator_name.strip()
        print(f"👤 Ghi nhớ người khởi tạo lệnh /storyfb: '{active_poll_initiator}'")

    try:
        print("📊 Đang tiến hành tạo Bình chọn Story FB trong nhóm Zalo...")
        send_zalo_message(d, "📊 Tẻn đang tạo Bảng Bình Chọn danh sách bạn bè để sếp lựa chọn nhé...")
        time.sleep(1)

        # 1. Mở ô Đính kèm (com.zing.zalo:id/new_chat_input_btn_attach)
        attach_btn = d(resourceId="com.zing.zalo:id/new_chat_input_btn_attach")
        if attach_btn.exists:
            attach_btn.click()
            time.sleep(1.5)
            
        poll_option = d(resourceId="com.zing.zalo:id/cel_option_polls") or d(text="Bình chọn")
        if poll_option.exists:
            poll_option.click()
            time.sleep(2)
            
        create_btn = d(resourceId="com.zing.zalo:id/btn_action") or d(text="TẠO BÌNH CHỌN")
        if create_btn.exists:
            create_btn.click()
            time.sleep(2)

        # 2. Nhập câu hỏi bình chọn
        question_input = d(resourceId="com.zing.zalo:id/et_group_poll_question")
        if question_input.exists:
            question_input.set_text("📊 Bạn muốn Tẻn kiểm tra Story Facebook của ai?")
            time.sleep(0.5)

        poll_names = [
            "Bình (Vo Bình)",
            "Huy (Huy Nguyễn)",
            "Vit (Pham Davit)",
            "Tâm (Nguyễn Trương Minh Tâm)",
            "Nhung (Nhung Trần)",
            "Mai (Huỳnh Phương Mai)",
            "Phương (Quảng Thị Minh Phương)",
            "Tuân"
        ]

        # 3. Điền 8 phương án (2 phương án đầu đã có sẵn trong Zalo)
        opts = d(resourceId="com.zing.zalo:id/et_group_poll_option")
        if len(opts) >= 1:
            opts[0].set_text(poll_names[0])
            time.sleep(0.2)
        if len(opts) >= 2:
            opts[1].set_text(poll_names[1])
            time.sleep(0.2)

        # Bấm thêm 6 phương án còn lại (Từ index 2 tới 7)
        for i in range(2, len(poll_names)):
            add_btn = d(resourceId="com.zing.zalo:id/btn_add_option") or d(text="Thêm phương án")
            if add_btn.exists:
                add_btn.click()
                time.sleep(0.3)
            
            opts_current = d(resourceId="com.zing.zalo:id/et_group_poll_option")
            if opts_current:
                opts_current[-1].set_text(poll_names[i])
                time.sleep(0.2)

        # 4. Tắt tùy chọn "Chọn nhiều phương án" & "Có thể thêm phương án"
        multi_switch = d(resourceId="com.zing.zalo:id/setting_multi_choice_switch")
        if multi_switch.exists and multi_switch.info.get("checked", False):
            print("🔘 Đang TẮT 'Chọn nhiều phương án'...")
            multi_switch.click()
            time.sleep(0.3)

        add_switch = d(resourceId="com.zing.zalo:id/setting_add_new_option_switch")
        if add_switch.exists and add_switch.info.get("checked", False):
            print("🔘 Đang TẮT 'Có thể thêm phương án'...")
            add_switch.click()
            time.sleep(0.3)

        # 5. Bấm nút TẠO
        submit_btn = d(resourceId="com.zing.zalo:id/actionbar_btn_trailing_1") or d(text="TẠO")
        if submit_btn.exists:
            submit_btn.click()
            print("✅ Đã tạo thành công Bảng Bình Chọn Story FB duy nhất trong nhóm Zalo!")
            time.sleep(2)
            return True
    except Exception as e:
        print(f"❌ Lỗi tạo Bình chọn Zalo: {e}")
    return False

def lock_and_cleanup_poll_zalo(d):
    """
    Tắt/Khóa Bảng Bình Chọn và quay về phòng chat Zalo an toàn không bị văng app:
    1. Click 'Khóa bình chọn' trên màn hình Chi tiết bình chọn.
    2. Bấm nút Back 2 lần để trở lại phòng chat Nà ná na na.
    """
    try:
        print("🧹 Đang tiến hành Khóa/Đóng Bảng Bình Chọn trong Zalo...")
        
        # Click 3 chấm góc trên bên phải màn hình Chi tiết bình chọn
        more_btn = (
            d(resourceId="com.zing.zalo:id/actionbar_btn_trailing_1") or 
            d(resourceId="com.zing.zalo:id/actionbar_btn_trailing_2") or 
            d(description="Xem thêm") or 
            d(description="Tùy chọn")
        )
        if more_btn.exists:
            more_btn.click()
            time.sleep(1.5)

            lock_item = d(text="Khóa bình chọn") or d(textContains="Khóa bình chọn")
            if lock_item.exists:
                lock_item.click()
                print("✅ Đã Khóa Bảng Bình Chọn thành công!")
                time.sleep(1.5)

        # Quay về phòng chat an toàn bằng nút Back
        for _ in range(3):
            if is_in_chat_room(d):
                break
            d.press("back")
            time.sleep(1.0)
            
        print("✅ Đã quay lại phòng chat Zalo an toàn!")
        return True
    except Exception as e:
        print(f"⚠️ Lỗi khóa/dọn dẹp bình chọn Zalo: {e}")
        # Đảm bảo vẫn quay về phòng chat nếu có lỗi
        start_zalo_and_open_chat(d, TARGET_GROUP_NAME)
    return False

def get_voted_friend_from_poll_screen(d):
    """
    Mở màn hình Chi tiết bình chọn, đọc vị trí Y của avatar người vote (com.zing.zalo:id/avt1)
    và đối chiếu chính xác 100% với tên phương án (tv_option) tại vị trí Y đó.
    """
    try:
        # Nếu chưa ở màn hình Chi tiết bình chọn, click mở thẻ bình chọn từ phòng chat
        if not d(resourceId="com.zing.zalo:id/tv_group_poll_question").exists:
            poll_card = (
                d(textContains="Bạn muốn Tẻn kiểm tra") or 
                d(textContains="cuộc bình chọn") or 
                d(textContains="bình chọn")
            )
            if poll_card.exists:
                poll_card.click()
                time.sleep(2)

        # 1. Lấy vị trí Y Center của Avatar người vote
        avt_elem = (
            d(resourceId="com.zing.zalo:id/avt1") or 
            d(resourceId="com.zing.zalo:id/avt2") or 
            d(resourceId="com.zing.zalo:id/avt3") or 
            d(resourceId="com.zing.zalo:id/no_votes_container")
        )
        
        avt_y = None
        if avt_elem.exists:
            b = avt_elem.info.get("bounds")
            if b:
                avt_y = (b["top"] + b["bottom"]) // 2
                print(f"🎯 [Poll Scanner] Đã tìm thấy Avatar người vote tại vị trí Y = {avt_y}")

        # 2. Duyệt qua tất cả phương án và đối chiếu tọa độ Y
        for opt in d(resourceId="com.zing.zalo:id/tv_option"):
            txt = opt.get_text() or ""
            b = opt.info.get("bounds")
            if txt and b:
                top_y = b["top"] - 20
                bot_y = b["bottom"] + 20
                if avt_y and (top_y <= avt_y <= bot_y):
                    print(f"✅ [Poll Scanner] Phát hiện phương án được chọn CHUẨN XÁC 100%: '{txt}'")
                    for friend_key, info in STORY_FRIENDS.items():
                        if friend_key in txt.lower() or info["name"].lower() in txt.lower():
                            return friend_key
    except Exception as e:
        print(f"⚠️ Lỗi quét phương án bình chọn: {e}")
    return None

def check_poll_vote_and_trigger(d, record):
    """
    Xử lý khi nhận được thông báo lượt bình chọn:
    1. Quét chính xác phương án được chọn bằng tọa độ Y Avatar trên màn hình Chi tiết bình chọn.
    2. Phân quyền: Chỉ phản hồi nếu đúng người gửi lệnh /storyfb.
    3. Mở FB Lite chụp Story -> Gửi ảnh Zalo -> Khóa & dọn dẹp Bảng Bình Chọn.
    """
    global active_poll_initiator
    voter_name = record.get("sender", "").strip()
    msg_text = record.get("content", "").strip()
    
    print(f"📊 [Poll Listener] Người bình chọn: '{voter_name}' | Người tạo lệnh: '{active_poll_initiator}' | Thông báo: '{msg_text}'")

    # 1. Phân quyền người dùng lệnh:
    if active_poll_initiator and voter_name and active_poll_initiator.lower() not in voter_name.lower() and voter_name.lower() not in active_poll_initiator.lower():
        print(f"⚠️ '{voter_name}' không phải người dùng lệnh '{active_poll_initiator}' -> Từ chối phản hồi!")
        send_zalo_message(d, f"⚠️ Chỉ có {active_poll_initiator} (người dùng lệnh /storyfb) mới có quyền chọn Story nhé!")
        return False

    # 2. Mở Chi tiết bình chọn và đối chiếu chính xác phương án bằng vị trí Avatar
    target_friend = get_voted_friend_from_poll_screen(d)
    if not target_friend:
        target_friend = "huy" # Fallback mặc định nếu không quét được

    print(f"🎯 [Poll Listener] Xác nhận lượt chọn CHUẨN XÁC 100% của {voter_name} cho bạn bè: '{target_friend}'")
    
    # 3. Kiểm tra Story FB Lite & gửi ảnh vào Zalo
    check_and_send_fb_story(d, target_friend)

    # 4. Khóa và dọn dẹp Bảng Bình Chọn Zalo
    lock_and_cleanup_poll_zalo(d)
    
    active_poll_initiator = "" # Reset người tạo lệnh
    return True

def exit_to_android_home(d):
    """Tắt sạch toàn bộ ứng dụng chạy ngầm (Zalo, Facebook Lite...) và quay về màn hình chính Android LDPlayer."""
    print("\n🧹 Đang dọn dẹp và tắt sạch toàn bộ ứng dụng chạy ngầm (Zalo, Facebook Lite)...")
    try:
        if d:
            d.app_stop(ZALO_PACKAGE)
            d.app_stop("com.facebook.lite")
            d.shell(f"am force-stop {ZALO_PACKAGE}")
            d.shell("am force-stop com.facebook.lite")
            time.sleep(0.5)
            d.press("home")
            time.sleep(1)
    except Exception as e:
        print(f"⚠️ Lỗi tắt ứng dụng ngầm: {e}")
    print("🛑 Bot đã tắt sạch ứng dụng ngầm và quay về màn hình chính an toàn!")

def check_and_send_fb_story(d, friend_keyword=None):
    """
    Tự động vào Facebook Lite (com.facebook.lite), kiểm tra Tin mới của bạn bè cụ thể:
    - Nếu là 'Tuân': Thông báo '⚠️ Tuân chưa đồng ý kết bạn với Tẻn nên chưa thể xem Story nhé!'
    - Các bạn bè khác: Mở FB Lite, xem Story, chụp ảnh màn hình và gửi vào Zalo.
    """
    if friend_keyword:
        key_clean = friend_keyword.strip().lower()
        if "tuân" in key_clean or "tuan" in key_clean:
            send_zalo_message(d, "⚠️ Tuân chưa đồng ý kết bạn với Tẻn nên chưa thể xem Story nhé!")
            return True

    # Tra cứu thông tin tên bạn bè
    target_info = None
    if friend_keyword:
        kw = friend_keyword.strip().lower()
        for k, info in STORY_FRIENDS.items():
            if k in kw or info["name"].lower() in kw:
                target_info = info
                break

    friend_disp_name = target_info["name"] if target_info else "bạn bè"
    print(f"🚀 Đang mở ứng dụng Facebook Lite để kiểm tra Story của: {friend_disp_name}...")
    send_zalo_message(d, f"🔎 Tẻn đang qua Facebook Lite kiểm tra Story của {friend_disp_name}...")

    try:
        d.app_start("com.facebook.lite")
        time.sleep(4)

        # Mở Tin mới của bạn bè
        opened_story = False
        if target_info and target_info["name"]:
            name_item = d(textContains=target_info["name"])
            if name_item.exists:
                name_item.click()
                opened_story = True
                time.sleep(3)

        if not opened_story:
            # Click ô Story thứ 2 tại X=450, Y=640
            d.click(450, 640)
            time.sleep(3)

        # Xử lý popup OK của Facebook Lite nếu lần đầu mở Tin
        if d(text="OK").exists:
            d(text="OK").click()
            time.sleep(2)

        # Chụp ảnh màn hình Story sắc nét
        print("📸 Đang chụp ảnh màn hình Story Facebook...")
        local_png = os.path.join(BASE_DIR, "temp_story_screenshot.png")
        d.screenshot(local_png)
        time.sleep(1)

        # Chuyển lại ứng dụng Zalo và mở phòng chat
        print("📲 Đang chuyển về Zalo để gửi ảnh Story...")
        start_zalo_and_open_chat(d, TARGET_GROUP_NAME)
        time.sleep(1)

        # Gửi ảnh vào nhóm Zalo
        send_zalo_photo_android(d, local_png)
        return True
    except Exception as e:
        print(f"❌ Lỗi kiểm tra Story FB Lite: {e}")
    return False

def send_zalo_photo_android(d, photo_path):
    """Gửi ảnh chụp màn hình Story vào nhóm Zalo qua LDPlayer."""
    try:
        abs_path = os.path.abspath(photo_path)
        if not os.path.exists(abs_path):
            print(f"❌ File ảnh không tồn tại: {abs_path}")
            return False

        remote_android_path = "/sdcard/DCIM/Camera/temp_story_screenshot.png"
        d.push(abs_path, remote_android_path)
        time.sleep(1)
        d.shell(f"am broadcast -a android.intent.action.MEDIA_SCANNER_SCAN_FILE -d file://{remote_android_path}")
        time.sleep(1.5)

        # Đảm bảo ở màn hình phòng chat
        if not is_in_chat_room(d):
            start_zalo_and_open_chat(d, TARGET_GROUP_NAME)
            time.sleep(1.5)

        print("🖼️ Đang mở Thư viện media Zalo...")
        photo_btn = d(resourceId="com.zing.zalo:id/new_chat_input_btn_show_gallery")
        if photo_btn.exists:
            photo_btn.click()
            time.sleep(2)
        else:
            d.click(850, 1110)
            time.sleep(2)

        # Chọn ô ảnh mới nhất tại X=450, Y=1309
        print("🎬 Đang chọn ảnh Story mới nhất...")
        d.click(450, 1309)
        time.sleep(1)

        send_btn = (
            d(resourceId="com.zing.zalo:id/btn_send") or 
            d(resourceId="com.zing.zalo:id/chat_btn_send") or 
            d(text="Gửi") or 
            d(textContains="Gửi")
        )
        if send_btn.exists:
            send_btn.click()
        else:
            d.click(820, 1550)

        print("🚀 Đã phát ảnh Story Facebook thành công vào nhóm Zalo!")
        time.sleep(3)

        cleanup_temp_videos(d, abs_path)
        return True
    except Exception as e:
        print(f"❌ Lỗi gửi ảnh Zalo: {e}")
        return False

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
                        send_zalo_message(d, "📜 [TẺN ANDROID BOT]\n- /ping\n- /menu\n- /video [link_fb_tt_yt]\n- /storyfb (Tạo Bảng Bình Chọn xem Story FB)\n- /storyfb [tên] (Ví dụ: /storyfb tâm, /storyfb tuân)\n- Gõ 'stop' ở CMD để tắt ứng dụng ngầm & về Home")
                    elif msg_text.startswith("/storyfb") or msg_text.startswith("/story"):
                        parts = msg_text.strip().split(maxsplit=1)
                        if len(parts) > 1:
                            target_name = parts[1].strip()
                            check_and_send_fb_story(d, target_name)
                        else:
                            create_story_poll_zalo(d, initiator_name=sender)
                    elif "cuộc bình chọn" in msg_text.lower() or "bình chọn" in msg_text.lower() or "tham gia" in msg_text.lower():
                        if "tạo cuộc bình chọn" not in msg_text.lower() and "đang tạo" not in msg_text.lower():
                            check_poll_vote_and_trigger(d, record)
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
