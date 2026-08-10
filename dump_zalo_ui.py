import uiautomator2 as u2
import xml.etree.ElementTree as ET
import os

def dump_ui():
    print("🔌 Đang kết nối tới LDPlayer (127.0.0.1:5555)...")
    try:
        d = u2.connect("127.0.0.1:5555")
        print(f"✅ Đã kết nối thành công: {d.info.get('productName', 'Android Device')}")
    except Exception as e:
        print(f"❌ Không thể kết nối ADB: {e}")
        return

    print("📱 Đang quét toàn bộ cây giao diện XML UI Automator của màn hình LDPlayer...")
    xml_content = d.dump_hierarchy()
    
    out_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "zalo_ui_dump.xml")
    with open(out_file, "w", encoding="utf-8") as f:
        f.write(xml_content)
    print(f"✅ Đã lưu toàn bộ cây XML giao diện tại: {out_file}\n")

    root = ET.fromstring(xml_content)
    print("🔍 ================= DANH SÁCH CÁC PHẦN TỬ GIAO DIỆN ================= 🔍")
    count = 0
    for elem in root.iter("node"):
        text = elem.attrib.get("text", "").strip()
        resource_id = elem.attrib.get("resource-id", "").strip()
        class_name = elem.attrib.get("class", "").strip()
        desc = elem.attrib.get("content-desc", "").strip()
        bounds = elem.attrib.get("bounds", "").strip()

        if text or resource_id or desc:
            count += 1
            info_parts = []
            if text:
                info_parts.append(f"Text: '{text}'")
            if resource_id:
                info_parts.append(f"ID: '{resource_id}'")
            if desc:
                info_parts.append(f"Desc: '{desc}'")
            info_parts.append(f"Class: '{class_name.split('.')[-1]}'")
            info_parts.append(f"Bounds: {bounds}")
            
            print(f"[{count:02d}] " + " | ".join(info_parts))

    print("\n🎉 Hoàn tất quét giao diện UI Automator!")

if __name__ == "__main__":
    dump_ui()
