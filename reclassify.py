#!/usr/bin/env python3
import requests
import subprocess
import os
import re
import concurrent.futures
import time

def download_file(url):
    """下载原始文件"""
    print(f"正在下载文件: {url}")
    try:
        response = requests.get(url, timeout=30)
        response.raise_for_status()
        print(f"下载成功，文件大小: {len(response.text)} 字符")
        return response.text
    except Exception as e:
        print(f"下载失败: {e}")
        return None

def process_content(content):
    """处理内容"""
    if not content:
        print("内容为空，无法处理")
        return []
        
    lines = content.split('\n')
    print(f"原始文件行数: {len(lines)}")
    
    # 1. 删除前两行
    if len(lines) >= 2:
        lines = lines[2:]
        print(f"删除前两行后行数: {len(lines)}")
    else:
        print("文件行数不足，无法删除前两行")
        return []
    
    # 2. 删除所有包含"-组播"的行
    filtered_lines = [line for line in lines if '-组播' not in line]
    print(f"删除'-组播'行后行数: {len(filtered_lines)}")
    
    # 只返回非空行
    non_empty_lines = [line for line in filtered_lines if line.strip()]
    print(f"非空行数: {len(non_empty_lines)}")
    
    # 打印前几行作为示例
    if non_empty_lines:
        print("前5行示例:")
        for i in range(min(5, len(non_empty_lines))):
            print(f"  {i+1}: {non_empty_lines[i]}")
    
    return non_empty_lines

def parse_groups(lines):
    """解析分组"""
    groups = {}
    current_group = None
    
    print("开始解析分组...")
    
    for line in lines:
        line = line.strip()
        if not line:
            continue
            
        # 检查是否是分组行
        if line.endswith(',#genre#'):
            group_name = line.split(',')[0]
            current_group = group_name
            groups[current_group] = []
            print(f"找到分组: {group_name}")
        elif current_group and ',' in line:
            # 频道行：频道名称,播放地址
            parts = line.split(',', 1)
            if len(parts) == 2:
                channel_name, channel_url = parts
                groups[current_group].append((channel_name, channel_url))
    
    print(f"共解析出 {len(groups)} 个分组")
    
    # 打印分组统计
    for group_name, channels in groups.items():
        print(f"分组 '{group_name}' 有 {len(channels)} 个频道")
    
    return groups

def check_stream(url, timeout=5):
    """
    使用ffprobe检查流有效性
    参考fofa_fetch.py中的检测方法
    """
    print(f"  检测流: {url}")
    
    try:
        result = subprocess.run(
            ["ffprobe", "-v", "error", "-show_streams", "-i", url],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout + 2
        )
        
        # 如果输出中包含"codec_type"，则认为流有效
        is_valid = b"codec_type" in result.stdout
        
        if is_valid:
            print(f"    ✓ 流有效")
        else:
            print(f"    ✗ 流无效")
            if result.stderr:
                error_msg = result.stderr.decode('utf-8', errors='ignore')[:100]
                print(f"    错误信息: {error_msg}")
        
        return is_valid
        
    except subprocess.TimeoutExpired:
        print(f"    ✗ 检测超时")
        return False
    except Exception as e:
        print(f"    ✗ 检测异常: {e}")
        return False

def check_group_validity(group_name, channels, timeout=5):
    """检查分组有效性"""
    if not channels:
        print(f"分组 '{group_name}' 没有频道，跳过")
        return False
    
    # 取第一个频道的播放地址进行检测
    first_channel_url = channels[0][1]
    
    print(f"检测分组 '{group_name}' 的第一个频道: {first_channel_url}")
    
    is_valid = check_stream(first_channel_url, timeout)
    
    if is_valid:
        print(f"✓ 分组 '{group_name}' 有效，保留")
        return True
    else:
        print(f"✗ 分组 '{group_name}' 无效，删除")
        return False

def filter_valid_groups(groups, max_workers=5):
    """使用多线程过滤有效的分组"""
    valid_groups = {}
    
    print("开始多线程检测流有效性...")
    
    # 准备检测任务
    tasks = []
    for group_name, channels in groups.items():
        if channels:  # 只检测有频道的分组
            tasks.append((group_name, channels))
    
    print(f"共有 {len(tasks)} 个分组需要检测")
    
    # 使用线程池并行检测
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        # 提交所有检测任务
        future_to_group = {
            executor.submit(check_group_validity, group_name, channels): group_name 
            for group_name, channels in tasks
        }
        
        # 收集结果
        for future in concurrent.futures.as_completed(future_to_group):
            group_name = future_to_group[future]
            try:
                is_valid = future.result()
                if is_valid:
                    valid_groups[group_name] = groups[group_name]
            except Exception as e:
                print(f"检测分组 '{group_name}' 时发生异常: {e}")
    
    print(f"有效性检测完成，有效分组: {len(valid_groups)} 个")
    return valid_groups

def generate_output(valid_groups):
    """生成输出内容"""
    output_lines = []
    
    print("生成输出内容...")
    
    for group_name, channels in valid_groups.items():
        print(f"处理分组 '{group_name}' 的 {len(channels)} 个频道")
        for channel_name, channel_url in channels:
            # 在播放地址后加入$所属组名
            output_line = f"{channel_name},{channel_url}${group_name}"
            output_lines.append(output_line)
    
    print(f"共生成 {len(output_lines)} 行输出")
    return '\n'.join(output_lines)

def main():
    # 原始文件URL
    url = "https://raw.githubusercontent.com/q1017673817/iptvz/main/zubo_all.txt"
    
    try:
        print("=== 开始处理 ===")
        start_time = time.time()
        
        print("步骤1: 下载文件...")
        content = download_file(url)
        if not content:
            print("下载失败，退出")
            return
        
        print("步骤2: 处理内容...")
        lines = process_content(content)
        if not lines:
            print("处理内容后没有有效行，退出")
            return
        
        print("步骤3: 解析分组...")
        groups = parse_groups(lines)
        if not groups:
            print("没有解析出任何分组，退出")
            return
        
        print("步骤4: 多线程检测流有效性...")
        valid_groups = filter_valid_groups(groups, max_workers=10)
        if not valid_groups:
            print("没有有效的分组，退出")
            return
        
        print("步骤5: 生成输出文件...")
        output_content = generate_output(valid_groups)
        
        # 写入文件
        with open('reclassify.txt', 'w', encoding='utf-8') as f:
            f.write(output_content)
        
        channel_count = len(output_content.splitlines())
        end_time = time.time()
        processing_time = end_time - start_time
        
        print(f"=== 完成！ ===")
        print(f"处理时间: {processing_time:.2f} 秒")
        print(f"有效分组: {len(valid_groups)} 个")
        print(f"总频道数: {channel_count} 个")
        print(f"生成文件: reclassify.txt")
        
    except Exception as e:
        print(f"错误: {e}")
        import traceback
        traceback.print_exc()
        exit(1)

if __name__ == "__main__":
    main()