import uiautomator2 as u2
import xml.etree.ElementTree as ET
import time
import os

def dump_drawer():
    d = u2.connect("127.0.0.1:5555")
    print("🚀 Opening Zalo app...")
    d.app_start("com.zing.zalo")
    time.sleep(3)

    if d(textContains="Nà ná na na").exists:
        print("👉 Clicking conversation item 'Nà ná na na'...")
        d(textContains="Nà ná na na").click()
        time.sleep(3)

    print("🖼️ Opening Media Picker Drawer inside chat room...")
    gallery_btn = d(resourceId="com.zing.zalo:id/new_chat_input_btn_show_gallery")
    if gallery_btn.exists:
        gallery_btn.click()
        time.sleep(3)
    else:
        print("⚠️ Not finding gallery_btn, clicking coordinate (850, 1550)...")
        d.click(850, 1550)
        time.sleep(3)

    print("📱 Dumping XML hierarchy of open Media Picker Drawer...")
    xml_content = d.dump_hierarchy()
    
    out_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "zalo_media_drawer_dump.xml")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(xml_content)
        
    print(f"✅ Saved XML dump to: {out_path}\n")

    root = ET.fromstring(xml_content)
    print("🔍 ================= MEDIA PICKER DRAWER NODES ================= 🔍")
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

if __name__ == "__main__":
    dump_drawer()
