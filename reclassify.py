#!/usr/bin/env python3
import requests
import subprocess
import tempfile
import os
import re

def download_file(url):
    """下载原始文件"""
    response = requests.get(url)
    response.raise_for_status()
    return response.text

def process_content(content):
    """处理内容"""
    lines = content.split('\n')
    
    # 1. 删除前两行
    lines = lines[2:]
    
    # 2. 删除所有包含"-组播"的行
    lines = [line for line in lines if '-组播' not in line]
    
    return lines

def parse_groups(lines):
    """解析分组"""
    groups = {}
    current_group = None
    
    for line in lines:
        line = line.strip()
        if not line:
            continue
            
        # 检查是否是分组行
        if line.endswith(',#genre#'):
            group_name = line.split(',')[0]
            current_group = group_name
            groups[current_group] = []
        elif current_group and ',' in line:
            # 频道行：频道名称,播放地址
            channel_name, channel_url = line.split(',', 1)
            groups[current_group].append((channel_name, channel_url))
    
    return groups

def check_stream_validity(url, timeout=5):
    """使用ffprobe检查流有效性"""
    try:
        cmd = [
            'ffprobe', 
            '-v', 'error',
            '-show_entries', 'format=duration',
            '-of', 'default=noprint_wrappers=1:nokey=1',
            '-timeout', str(timeout * 1000000),  # 微秒
            url
        ]
        result = subprocess.run(
            cmd, 
            stdout=subprocess.PIPE, 
            stderr=subprocess.PIPE,
            timeout=timeout + 2
        )
        return result.returncode == 0
    except (subprocess.TimeoutExpired, subprocess.SubprocessError):
        return False

def filter_valid_groups(groups):
    """过滤有效的分组"""
    valid_groups = {}
    
    for group_name, channels in groups.items():
        if not channels:
            continue
            
        # 取第一个频道的播放地址进行检测
        first_channel_url = channels[0][1]
        
        print(f"检测分组 '{group_name}' 的第一个频道: {first_channel_url}")
        
        if check_stream_validity(first_channel_url):
            valid_groups[group_name] = channels
            print(f"分组 '{group_name}' 有效，保留")
        else:
            print(f"分组 '{group_name}' 无效，删除")
    
    return valid_groups

def generate_output(valid_groups):
    """生成输出内容"""
    output_lines = []
    
    for group_name, channels in valid_groups.items():
        for channel_name, channel_url in channels:
            # 在播放地址后加入$所属组名
            output_line = f"{channel_name},{channel_url}${group_name}"
            output_lines.append(output_line)
    
    return '\n'.join(output_lines)

def main():
    # 原始文件URL
    url = "https://raw.githubusercontent.com/q1017673817/iptvz/main/zubo_all.txt"
    
    try:
        print("开始下载文件...")
        content = download_file(url)
        
        print("处理内容...")
        lines = process_content(content)
        
        print("解析分组...")
        groups = parse_groups(lines)
        print(f"找到 {len(groups)} 个分组")
        
        print("检测流有效性...")
        valid_groups = filter_valid_groups(groups)
        print(f"有效分组: {len(valid_groups)} 个")
        
        print("生成输出文件...")
        output_content = generate_output(valid_groups)
        
        # 写入文件
        with open('reclassify.txt', 'w', encoding='utf-8') as f:
            f.write(output_content)
        
        print(f"完成！生成 reclassify.txt，包含 {len(output_content.splitlines())} 个频道")
        
    except Exception as e:
        print(f"错误: {e}")
        exit(1)

if __name__ == "__main__":
    main()