import requests
import subprocess
import concurrent.futures
import sys
from collections import defaultdict

def download_file(url):
    """下载原始配置文件"""
    print("正在下载配置文件...")
    try:
        response = requests.get(url, timeout=30)
        response.raise_for_status()
        return response.text
    except requests.RequestException as e:
        print(f"下载文件失败: {e}")
        sys.exit(1)

def remove_first_two_lines(content):
    """删除前两行"""
    lines = content.split('\n')
    return '\n'.join(lines[2:])

def remove_multicast_chars(content):
    """删除所有-组播字符"""
    return content.replace('-组播', '')

def parse_groups(content):
    """解析分组和频道信息"""
    groups = {}
    current_group = None
    current_channels = []
    
    lines = content.split('\n')
    for line in lines:
        line = line.strip()
        if not line:
            continue
            
        if '#genre#' in line:
            # 保存上一个分组
            if current_group and current_channels:
                groups[current_group] = current_channels
            
            # 开始新分组
            current_group = line.split(',#genre#')[0]
            current_channels = []
        elif current_group and ',' in line:
            # 频道行
            parts = line.split(',', 1)
            if len(parts) == 2:
                channel_name, channel_url = parts
                current_channels.append((channel_name, channel_url))
    
    # 保存最后一个分组
    if current_group and current_channels:
        groups[current_group] = current_channels
    
    return groups

def check_stream(url, timeout=5):
    """使用ffprobe检测流是否有效"""
    try:
        result = subprocess.run(
            ["ffprobe", "-v", "error", "-show_streams", "-i", url],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout + 2
        )
        return b"codec_type" in result.stdout
    except Exception as e:
        print(f"检测失败 {url}: {e}")
        return False

def test_group_first_channel(group_name, channels):
    """测试分组第一个频道的有效性"""
    if not channels:
        return group_name, False
    
    first_channel_name, first_channel_url = channels[0]
    print(f"测试分组 '{group_name}' 的第一个频道: {first_channel_name}")
    
    is_valid = check_stream(first_channel_url)
    if is_valid:
        print(f"✓ 分组 '{group_name}' 有效")
    else:
        print(f"✗ 分组 '{group_name}' 无效")
    
    return group_name, is_valid

def test_groups(groups, max_workers=5):
    """测试所有分组的有效性"""
    print(f"🚀 启动多线程检测（共 {len(groups)} 个分组）...")
    valid_groups = {}
    
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_group = {
            executor.submit(test_group_first_channel, group_name, channels): group_name 
            for group_name, channels in groups.items()
        }
        
        for future in concurrent.futures.as_completed(future_to_group):
            group_name, is_valid = future.result()
            if is_valid:
                valid_groups[group_name] = groups[group_name]
    
    print(f"✅ 检测完成，有效分组共 {len(valid_groups)} 个")
    return valid_groups

def process_valid_channels(valid_groups):
    """处理有效频道，生成平表格式"""
    flat_channels = []
    seen_channels = set()
    
    for group_name, channels in valid_groups.items():
        for channel_name, channel_url in channels:
            channel_key = f"{channel_name}|{channel_url}"
            if channel_key not in seen_channels:
                seen_channels.add(channel_key)
                # 在URL后添加$运营商分组
                processed_url = f"{channel_url}${group_name}"
                flat_channels.append((channel_name, processed_url))
    
    return flat_channels

def save_flat_channels(channels, output_file):
    """保存平表格式的频道列表"""
    with open(output_file, 'w', encoding='utf-8') as f:
        for channel_name, channel_url in channels:
            f.write(f"{channel_name},{channel_url}\n")
    
    print(f"平表格式已保存到: {output_file}")
    print(f"共生成 {len(channels)} 个有效频道")

def main():
    url = "https://raw.githubusercontent.com/q1017673817/iptvz/main/zubo_all.txt"
    
    try:
        # 1. 下载文件
        content = download_file(url)
        
        # 2. 删除前两行
        content = remove_first_two_lines(content)
        
        # 3. 删除-组播字符
        content = remove_multicast_chars(content)
        
        # 4. 解析原始分组
        original_groups = parse_groups(content)
        print(f"找到 {len(original_groups)} 个原始分组")
        
        # 5. 测试分组有效性
        valid_groups = test_groups(original_groups, max_workers=3)
        
        # 6. 处理有效频道，生成平表
        flat_channels = process_valid_channels(valid_groups)
        
        # 7. 保存平表格式
        flat_output_file = "flat_iptv_list.txt"
        save_flat_channels(flat_channels, flat_output_file)
                
    except Exception as e:
        print(f"处理过程中出现错误: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    main()
