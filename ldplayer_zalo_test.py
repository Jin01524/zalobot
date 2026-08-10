import time
import os
import re
import uuid
import requests
import uiautomator2 as u2

# Cấu hình địa chỉ ADB LDPlayer (Mặc định LDPlayer 9 là 127.0.0.1:5555 hoặc 127.0.0.1:62001)
LDPLAYER_ADB = "127.0.0.1:5555" 
ZALO_PACKAGE = "com.zing.zalo"
TARGET_GROUP_NAME = "Nà ná na na"  # Tên nhóm chat mẫu
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

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
    Tự động trích xuất ID số (10-20 chữ số) từ link share/watch/reel/fb.watch để tránh lỗi yt-dlp.
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
    """Tải video đa nền tảng bằng yt-dlp trực tiếp."""
    target_url = normalize_video_url(target_url)
    try:
        import yt_dlp
        unique_id = str(uuid.uuid4())[:8]
        out_template = os.path.join(output_dir, f"temp_video_{unique_id}.%(ext)s")
        ydl_opts = {
            'format': 'bestvideo[vcodec^=avc1][ext=mp4]+bestaudio[acodec^=mp4a]/bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best',
            'merge_output_format': 'mp4',
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
    """Kiểm tra xem hiện tại có phải đang ở trong màn hình phòng chat hay không."""
    return (
        d(resourceId="com.zing.zalo:id/chat_input_text").exists or 
        d(resourceId="com.zing.zalo:id/input_chat").exists or 
        d(resourceId="com.zing.zalo:id/chat_btn_send").exists
    )

def start_zalo_and_open_chat(d, group_name):
    print("🚀 Đang khởi động ứng dụng Zalo...")
    d.app_start(ZALO_PACKAGE)
    time.sleep(4)  # Chờ 4s cho Zalo Android mở hẳn

    # 1. Nếu đã ở trong phòng chat sẵn
    if is_in_chat_room(d):
        print(f"✅ Đã ở trong phòng chat sẵn.")
        return True

    # 2. Thử click trực tiếp vào nhóm nếu đã hiển thị ngay màn hình danh sách tin nhắn
    group_item = d(text=group_name)
    if group_item.exists and not d(resourceId="com.zing.zalo:id/search_src_text").exists:
        group_item.click()
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

    # Debug: In ra tất cả text hiện tại trên màn hình Zalo để soi Selector
    print("ℹ️ Danh sách chữ hiện trên màn hình LDPlayer hiện tại:")
    try:
        visible_texts = [el.get_text() for el in d(className="android.widget.TextView") if el.get_text()]
        print("   " + ", ".join(visible_texts[:15]))
    except Exception:
        pass

    print(f"❌ Không mở được phòng chat: '{group_name}'")
    return False

def send_zalo_message(d, text_msg):
    """Gửi tin nhắn văn bản (CHỈ GỬI KHI ĐÃ Ở TRONG PHÒNG CHAT)."""
    try:
        input_box = None
        selectors = [
            d(resourceId="com.zing.zalo:id/chat_input_text"),
            d(resourceId="com.zing.zalo:id/input_chat"),
            d(resourceId="com.zing.zalo:id/input_chat_text"),
            d(text="Tin nhắn"),
            d(textContains="Tin nhắn"),
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
    Gửi Video MXH trực tiếp vào nhóm chat Zalo Android qua LDPlayer:
    1. Push file .mp4 từ máy tính vào thẻ nhớ Android (/sdcard/DCIM/Camera/temp_bot_video.mp4).
    2. Gọi MediaScanner để Zalo Android cập nhật video mới vào Thư viện.
    3. Mở Bộ chọn Thư viện của Zalo, chọn video mới nhất và bấm Gửi HD.
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
        photo_btn = None
        photo_selectors = [
            d(resourceId="com.zing.zalo:id/btn_photo"),
            d(resourceId="com.zing.zalo:id/stk_btn_photo"),
            d(resourceId="com.zing.zalo:id/chat_btn_photo"),
            d(description="Ảnh"),
            d(description="Thư viện"),
            d.xpath("//*[contains(@resource-id, 'photo') or contains(@resource-id, 'media') or contains(@resource-id, 'gallery')]")
        ]
        for p_sel in photo_selectors:
            if p_sel.exists:
                photo_btn = p_sel
                break

        if photo_btn:
            photo_btn.click()
            time.sleep(2)
        else:
            # Click icon Thư viện ảnh ở thanh dưới bên phải ô nhập tin nhắn
            d.click(660, 1220)
            time.sleep(2)

        # Bật chế độ HD nếu có
        hd_option = d(resourceId="com.zing.zalo:id/btn_hd") or d(text="HD")
        if hd_option.exists:
            try:
                hd_option.click()
                time.sleep(0.5)
            except Exception:
                pass

        # Chọn video đầu tiên trong thư viện (Mới nhất ở góc trên bên trái)
        print("🎬 Đang chọn video mới nhất...")
        grid_items = (
            d(resourceId="com.zing.zalo:id/grid_item_photo") or 
            d(resourceId="com.zing.zalo:id/iv_thumb") or 
            d(resourceId="com.zing.zalo:id/v_photo_picker") or
            d.xpath("//android.widget.GridView/*[1]")
        )
        if grid_items.exists:
            grid_items.click()
            time.sleep(1)
        else:
            # Click ô đầu tiên trong grid chọn media
            d.click(120, 950)
            time.sleep(1)

        # Nhấp nút Gửi
        send_btn = (
            d(resourceId="com.zing.zalo:id/btn_send") or 
            d(resourceId="com.zing.zalo:id/chat_btn_send") or 
            d(text="Gửi") or
            d(textContains="Gửi")
        )
        if send_btn.exists:
            send_btn.click()
            print("🚀 Đã phát video thành công vào nhóm Zalo Android!")
            time.sleep(3)

        # Xóa file tạm trên Android sdcard
        d.shell(f"rm -f {remote_android_path}")
        return True
    except Exception as e:
        print(f"❌ Lỗi gửi video Android: {e}")
        return False

def get_latest_chat_message(d):
    """Đọc nội dung tin nhắn văn bản mới nhất trong màn hình chat."""
    try:
        msg_selectors = [
            d(resourceId="com.zing.zalo:id/tv_message"),
            d(resourceId="com.zing.zalo:id/chat_message_text"),
            d(resourceId="com.zing.zalo:id/message_text"),
            d(resourceId="com.zing.zalo:id/cell_title_tv")
        ]
        for sel in msg_selectors:
            if sel.exists:
                messages = [el for el in sel if el.get_text()]
                if messages:
                    return messages[-1].get_text()
    except Exception:
        pass
    return None

def main():
    d = init_ldplayer()
    if not d:
        return

    # Mở Zalo & Nhóm Chat
    if start_zalo_and_open_chat(d, TARGET_GROUP_NAME):
        send_zalo_message(d, "🤖 Tẻn Android Bot (LDPlayer) đã kết nối trực tiếp thành công!")
        
        print("👁️ Bắt đầu vòng lặp lắng nghe tin nhắn Zalo Android...")
        last_text = ""
        try:
            while True:
                msg_text = get_latest_chat_message(d)
                if msg_text and msg_text != last_text:
                    last_text = msg_text
                    print(f"📩 Tin nhắn mới nhận: {msg_text}")
                    
                    if msg_text.startswith("/ping"):
                        send_zalo_message(d, "🏓 Pong! Bot LDPlayer đang phản hồi cực nhanh!")
                    elif msg_text.startswith("/menu"):
                        send_zalo_message(d, "📜 [TẺN ANDROID BOT]\n- /ping\n- /menu\n- /video [link_fb_tt_yt]\n- Tải video HD phát mượt 100%!")
                    elif msg_text.startswith("/video") or msg_text.startswith("/v ") or any(domain in msg_text for domain in ["facebook.com", "fb.watch", "tiktok.com", "youtube.com", "youtu.be"]):
                        url_match = re.search(r'(https?://[^\s]+)', msg_text)
                        if url_match:
                            target_url = url_match.group(1)
                            send_zalo_message(d, "⏳ Tẻn đang tải video MXH về nhóm, sếp chờ xíu nhé...")
                            v_file = download_video_web(target_url, BASE_DIR)
                            if v_file:
                                send_zalo_video_android(d, v_file)
                                try:
                                    if os.path.exists(v_file):
                                        os.remove(v_file)
                                except Exception:
                                    pass
                            else:
                                send_zalo_message(d, "❌ Không thể tải video từ liên kết này!")

                time.sleep(1)
        except KeyboardInterrupt:
            print("\n🛑 Đã dừng test bot LDPlayer.")

if __name__ == "__main__":
    main()
