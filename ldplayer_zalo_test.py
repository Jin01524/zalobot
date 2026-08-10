import time
import os
import uiautomator2 as u2

# Cấu hình địa chỉ ADB LDPlayer (Mặc định LDPlayer 9 là 127.0.0.1:5555 hoặc 127.0.0.1:62001)
LDPLAYER_ADB = "127.0.0.1:5555" 
ZALO_PACKAGE = "com.zing.zalo"
TARGET_GROUP_NAME = "Nà ná na na"  # Tên nhóm chat mẫu

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
                time.sleep(2.5)
                
                # Tìm và click dòng kết quả tìm kiếm (Bỏ qua ô EditText tìm kiếm)
                results = d(text=group_name) or d(textContains=group_name)
                if results.exists:
                    for i in range(len(results)):
                        item = results[i]
                        # Bỏ qua ô nhập tìm kiếm
                        if item.info.get("className") != "android.widget.EditText":
                            item.click()
                            time.sleep(2.5)
                            if is_in_chat_room(d):
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
        # 🧠 Bắt buộc lấy ô chat input trong phòng chat (resourceId chứa chat_input/input_chat)
        input_box = d(resourceId="com.zing.zalo:id/chat_input_text") or d(resourceId="com.zing.zalo:id/input_chat")
        
        # Nếu chưa tìm thấy resourceId chuẩn nhưng xác nhận đã ở trong phòng chat
        if not input_box.exists and is_in_chat_room(d):
            input_box = d(className="android.widget.EditText")

        if input_box.exists:
            input_box.set_text(text_msg)
            time.sleep(0.5)
            send_btn = (
                d(resourceId="com.zing.zalo:id/btn_send") or 
                d(resourceId="com.zing.zalo:id/chat_btn_send") or 
                d(description="Gửi")
            )
            if send_btn.exists:
                send_btn.click()
                print(f"📤 Đã gửi tin nhắn: {text_msg}")
                return True
        else:
            print("⚠️ Không tìm thấy ô nhập tin nhắn trong phòng chat!")
    except Exception as e:
        print(f"⚠️ Lỗi gửi tin nhắn: {e}")
    return False

def get_latest_chat_message(d):
    """Đọc nội dung tin nhắn văn bản mới nhất trong màn hình chat."""
    try:
        messages = d(resourceId="com.zing.zalo:id/chat_message_text")
        if messages.exists and len(messages) > 0:
            latest_text = messages[-1].get_text()
            return latest_text
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
                        send_zalo_message(d, "📜 [TẺN ANDROID BOT]\n- /ping\n- /menu\n- Tải video HD phát mượt 100%!")
                        
                time.sleep(1)
        except KeyboardInterrupt:
            print("\n🛑 Đã dừng test bot LDPlayer.")

if __name__ == "__main__":
    main()
