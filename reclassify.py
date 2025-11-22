import subprocess
import re
import os
import requests
from typing import List, Dict, Tuple
from concurrent.futures import ThreadPoolExecutor, as_completed
import time

def download_txt(txt_url: str, local_path: str) -> bool:
    """从Github下载TXT文件（适配仓库RAW地址）"""
    try:
        response = requests.get(txt_url, timeout=15, headers={"User-Agent": "Mozilla/5.0"})
        response.raise_for_status()
        with open(local_path, 'w', encoding='utf-8', errors='ignore') as f:
            f.write(response.text)
        print(f"✅ 成功下载TXT文件：{txt_url}")
        return True
    except Exception as e:
        print(f"❌ 下载失败：{str(e)}")
        return False

def load_and_clean_txt(file_path: str) -> List[str]:
    """基础清理：删除前两行、移除-组播、过滤空行"""
    with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
        lines = f.readlines()
    # 删除前两行（确保兼容行数不足场景）
    cleaned_lines = lines[2:] if len(lines) >= 2 else lines
    # 清理内容：移除-组播、去重空行、strip首尾空格
    cleaned_lines = [
        line.replace('-组播', '').strip() 
        for line in cleaned_lines 
        if line.strip() and not line.startswith('#EXTM3U')  # 过滤无效空行和M3U头
    ]
    return cleaned_lines

def parse_groups(cleaned_lines: List[str]) -> Dict[str, List[Tuple[str, str]]]:
    """解析分组数据：key=组名，value=[(频道名称, 播放地址), ...]"""
    groups: Dict[str, List[Tuple[str, str]]] = {}
    current_group = ""
    for line in cleaned_lines:
        if line.startswith('#genre#'):
            # 提取组名（兼容逗号分隔和纯文本组名）
            group_match = re.search(r'#genre#(.+?)(?:,|$)', line)
            current_group = group_match.group(1).strip() if group_match else ""
            if current_group and current_group not in groups:
                groups[current_group] = []
        else:
            # 解析频道（兼容多逗号场景，取第一个逗号分隔）
            if ',' in line and current_group:
                name, url = line.split(',', 1)
                name = name.strip()
                url = url.strip()
                if url.startswith(('http://', 'https://', 'rtsp://', 'rtmp://', 'm3u8://')):
                    groups[current_group].append((name, url))
    return groups

def check_url_validity(url: str, timeout: int = 5, retries: int = 1) -> bool:
    """优化ffprobe检测逻辑：超时重试+精简参数+错误抑制"""
    cmd = [
        'ffprobe', '-v', 'panic',  # 仅输出严重错误（减少日志）
        '-show_entries', 'format=duration',
        '-of', 'default=noprint_wrappers=1:nokey=1',
        '-timeout', f'{timeout * 1000000}',  # 微秒单位
        '-rtsp_transport', 'tcp',  # RTSP协议强制TCP（提升兼容性）
        url
    ]
    
    for attempt in range(retries + 1):
        try:
            result = subprocess.run(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                check=True, timeout=timeout + 3,  # 预留缓冲时间
                encoding='utf-8', shell=False  # 禁用shell（安全+适配Github环境）
            )
            # 验证时长（非空+数字格式）
            duration = result.stdout.strip()
            if duration and (duration.replace('.', '').isdigit()):
                return True
        except subprocess.TimeoutExpired:
            if attempt < retries:
                print(f"⚠️  地址超时，重试第{attempt + 1}次：{url}")
                time.sleep(1)  # 重试间隔
            else:
                print(f"❌ 地址超时（已达最大重试）：{url}")
        except (subprocess.CalledProcessError, Exception) as e:
            # 忽略非致命错误（如协议不支持）
            if attempt == retries:
                print(f"❌ 地址无效：{url}（错误：{str(e)[:50]}）")
    return False

def filter_valid_groups(groups: Dict[str, List[Tuple[str, str]]], max_workers: int = 8) -> Dict[str, List[Tuple[str, str]]]:
    """多线程批量检测（提升Github运行效率）"""
    valid_groups: Dict[str, List[Tuple[str, str]]] = {}
    group_list = list(groups.items())
    
    print(f"🔍 开始检测 {len(group_list)} 个分组（每个分组仅检测第一个频道，{max_workers}线程并行）")
    
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        # 提交检测任务
        future_to_group = {
            executor.submit(check_url_validity, channels[0][1]): (group_name, channels)
            for group_name, channels in group_list
            if channels  # 跳过空分组
        }
        
        # 处理检测结果
        for future in as_completed(future_to_group):
            group_name, channels = future_to_group[future]
            try:
                is_valid = future.result()
                if is_valid:
                    valid_groups[group_name] = channels
                    print(f"✅ 有效分组：{group_name}（频道数：{len(channels)}）")
            except Exception as e:
                print(f"⚠️  分组检测异常 {group_name}：{str(e)}")
    
    print(f"\n📊 检测完成：有效分组 {len(valid_groups)}/{len(group_list)}")
    return valid_groups

def generate_flat_output(valid_groups: Dict[str, List[Tuple[str, str]]]) -> List[str]:
    """生成平表：频道名称,播放地址$组名（取消重分类+移除M3U头）"""
    flat_lines = []
    for group_name, channels in valid_groups.items():
        for name, url in channels:
            # 组名特殊字符转义（避免分隔符冲突）
            safe_group = group_name.replace(',', '，').replace('$', '￥')
            flat_lines.append(f"{name},{url}${safe_group}")
    return flat_lines

def save_flat_result(lines: List[str], output_path: str = "reclassify.txt"):
    """保存平表结果（输出文件名为reclassify.txt，无M3U头）"""
    with open(output_path, 'w', encoding='utf-8') as f:
        for line in lines:
            f.write(f"{line}\n")
    print(f"\n📄 平表结果已保存：{os.path.abspath(output_path)}（共{len(lines)}条频道）")

if __name__ == "__main__":
    # 配置参数（Github仓库RAW地址，直接可访问）
    TXT_URL = "https://raw.githubusercontent.com/q1017673817/iptvz/main/zubo_all.txt"
    LOCAL_TXT_PATH = "zubo_all.txt"
    MAX_WORKERS = 8  # 线程数（适配Github Actions资源）
    FFPROBE_TIMEOUT = 5  # 检测超时时间（秒）
    FFPROBE_RETRIES = 1  # 超时重试次数

    # 1. 下载TXT文件
    if not download_txt(TXT_URL, LOCAL_TXT_PATH):
        exit(1)

    # 2. 基础清理
    print("\n🔧 执行基础清理...")
    cleaned_lines = load_and_clean_txt(LOCAL_TXT_PATH)
    print(f"📥 清理后有效行数：{len(cleaned_lines)}")

    # 3. 解析分组
    print("\n📊 解析分组数据...")
    groups = parse_groups(cleaned_lines)
    print(f"📈 解析到分组数：{len(groups)}")

    # 4. 多线程过滤有效分组
    print("\n" + "="*50)
    valid_groups = filter_valid_groups(groups, max_workers=MAX_WORKERS)
    print("="*50 + "\n")

    # 5. 生成平表
    print("📝 生成平表数据...")
    flat_lines = generate_flat_output(valid_groups)

    # 6. 保存结果
    save_flat_result(flat_lines)

    # 清理临时文件（可选，Github Actions自动清理）
    if os.path.exists(LOCAL_TXT_PATH):
        os.remove(LOCAL_TXT_PATH)
        print(f"🗑️  清理临时文件：{LOCAL_TXT_PATH}")
