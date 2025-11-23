import requests
import subprocess
import os
import re
import concurrent.futures
import time
from datetime import datetime, timedelta

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
    
    # 只返回非空行
    non_empty_lines = [line for line in lines if line.strip()]
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
            # 提取组名并删除"-组播"字符串
            group_name = line.split(',')[0]
            # 删除组名中的"-组播"字符串
            group_name = group_name.replace('-组播', '')
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

def check_stream(url, timeout=8):
    """
    使用ffprobe检查流有效性 - 优化版本
    """
    print(f"  检测流: {url}")
    
    try:
        # 使用更宽松的参数检测流
        result = subprocess.run(
            [
                "ffprobe", 
                "-v", "quiet",
                "-probesize", "32",
                "-analyzeduration", "1000000",  # 1秒
                "-select_streams", "v:0",  # 只检测视频流
                "-show_entries", "stream=codec_type",
                "-of", "csv=p=0",
                "-i", url
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout
        )
        
        # 检查返回码和输出
        if result.returncode == 0:
            # 检查输出中是否包含视频流
            output = result.stdout.decode('utf-8', errors='ignore').strip()
            is_valid = "video" in output.lower()
            
            if is_valid:
                print(f"    ✓ 流有效")
            else:
                print(f"    ✗ 流无效 - 无视频流")
                if result.stderr:
                    error_msg = result.stderr.decode('utf-8', errors='ignore')[:200]
                    print(f"    错误信息: {error_msg}")
            
            return is_valid
        else:
            print(f"    ✗ 流无效 - 返回码: {result.returncode}")
            if result.stderr:
                error_msg = result.stderr.decode('utf-8', errors='ignore')[:200]
                print(f"    错误信息: {error_msg}")
            return False
        
    except subprocess.TimeoutExpired:
        print(f"    ✗ 检测超时 ({timeout}秒)")
        return False
    except FileNotFoundError:
        print(f"    ✗ 未找到ffprobe，请安装ffmpeg")
        return False
    except Exception as e:
        print(f"    ✗ 检测异常: {e}")
        return False

def check_group_validity(group_name, channels, timeout=8):
    """检查分组有效性 - 优化版本"""
    if not channels:
        print(f"分组 '{group_name}' 没有频道，跳过")
        return False
    
    # 尝试检测前3个频道，只要有一个有效就认为分组有效
    print(f"检测分组 '{group_name}' 的频道...")
    
    valid_count = 0
    tested_count = min(3, len(channels))  # 最多测试3个频道
    
    for i in range(tested_count):
        channel_name, channel_url = channels[i]
        print(f"  测试频道 {i+1}/{tested_count}: {channel_name}")
        
        is_valid = check_stream(channel_url, timeout)
        if is_valid:
            valid_count += 1
            print(f"  ✓ 频道有效，分组标记为有效")
            break  # 只要有一个有效就认为分组有效
        else:
            print(f"  ✗ 频道无效")
    
    is_group_valid = valid_count > 0
    
    if is_group_valid:
        print(f"✓ 分组 '{group_name}' 有效，保留")
    else:
        print(f"✗ 分组 '{group_name}' 无效，删除")
    
    return is_group_valid

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

def load_category_mapping():
    """加载频道分类映射 - 完整版本"""
    # 完整的分类映射
    CATEGORY_MAPPING = {
        "央视频道,#genre#": [
            "CCTV-1综合","CCTV-2财经","CCTV-3综艺","CCTV-4中文国际","CCTV-5体育","CCTV-5+体育赛事",
            "CCTV-6电影","CCTV-7国防军事","CCTV-8电视剧","CCTV-9纪录","CCTV-10科教","CCTV-11戏曲",
            "CCTV-12社会与法","CCTV-13新闻","CCTV-14少儿","CCTV-15音乐","CCTV-16奥林匹克",
            "CCTV-16奥林匹克4K","CCTV-17农业农村","CCTV-4欧洲","CCTV-4美洲","CCTV-4K","CCTV-8K",
            "中央新影-中学生","中央新影-老故事","中央新影-发现之旅","CGTN","CGTN-纪录","CGTN-法语",
            "CGTN-俄语","CGTN-西班牙语","CGTN-阿拉伯语","中国教育1台","中国教育2台","中国教育4台","早期教育"
        ],
        "付费频道,#genre#": [
            "CCTV风云剧场","CCTV怀旧剧场","CCTV第一剧场","CCTV风云足球","CCTV央视台球",
            "CCTV高尔夫·网球","CCTV风云音乐","CCTV央视文化精品","CCTV卫生健康","CCTV电视指南",
            "CCTV兵器科技","CCTV女性时尚","CCTV世界地理","CHC家庭影院","CHC动作电影","CHC影迷电影"
        ],
        "卫视频道,#genre#": [
            "山东卫视","北京卫视","东方卫视","重庆卫视","江苏卫视","浙江卫视","江西卫视","安徽卫视",
            "湖南卫视","湖北卫视","河南卫视","河北卫视","广东卫视","广西卫视","深圳卫视","大湾区卫视",
            "东南卫视","海南卫视","四川卫视","贵州卫视","云南卫视","天津卫视","辽宁卫视","黑龙江卫视",
            "吉林卫视","内蒙古卫视","宁夏卫视","山西卫视","陕西卫视","甘肃卫视","青海卫视","新疆卫视",
            "西藏卫视","三沙卫视","兵团卫视","延边卫视","安多卫视","康巴卫视","农林卫视","海峡卫视",
            "山东教育卫视","西藏卫视藏语","安多卫视藏语","康巴卫视藏语","内蒙古卫视蒙语",
            "北京卫视4K","广东卫视4K","深圳卫视4K","山东卫视4K","湖南卫视4K","浙江卫视4K",
            "江苏卫视4K","东方卫视4K","四川卫视4K"
        ],
        "国际频道,#genre#": [
            "凤凰卫视","凤凰资讯","凤凰香港","凤凰电影","星空卫视","Channel[V]"
        ],
        # 其他省份频道分类保持不变...
        "其他频道,#genre#": []
    }

    # 简化的频道名称映射
    CHANNEL_NAME_MAPPING = {
        "CCTV-1综合": ["CCTV-1综合"],
        "CCTV-2财经": ["CCTV-2财经"],
        "CCTV-3综艺": ["CCTV-3综艺"],
        "CCTV-4中文国际": ["CCTV-4中文国际"],
        "CCTV-5体育": ["CCTV-5体育"],
        "CCTV-5+体育赛事": ["CCTV-5+体育赛事","CCTV5+体育赛事"],
        "CCTV-6电影": ["CCTV-6电影"],
        "CCTV-7国防军事": ["CCTV-7国防军事"],
        "CCTV-8电视剧": ["CCTV-8电视剧"],
        "CCTV-9纪录": ["CCTV-9纪录"],
        "CCTV-10科教": ["CCTV-10科教"],
        "CCTV-11戏曲": ["CCTV-11戏曲"],
        "CCTV-12社会与法": ["CCTV-12社会与法"],
        "CCTV-13新闻": ["CCTV-13新闻"],
        "CCTV-14少儿": ["CCTV-14少儿"],
        "CCTV-15音乐": ["CCTV-15音乐"],
        "CCTV-16奥林匹克": ["CCTV-16奥林匹克"],
        "CCTV-16奥林匹克4K": ["CCTV-16奥林匹克4K"],
        "CCTV-17农业农村": ["CCTV-17农业农村"],
        "CCTV-4欧洲": ["CCTV4欧洲","CCTV-4欧洲","CCTV4欧洲 HD","CCTV-4 欧洲","CCTV-4中文国际欧洲","CCTV-4中文国际 欧洲"],
        "CCTV-4美洲": ["CCTV4美洲","CCTV-4北美","CCTV4美洲 HD","CCTV-4 美洲","CCTV-4中文国际美洲","CCTV-4中文国际 美洲"],
        "CCTV-4K": ["CCTV4K超高清","CCTV4K","CCTV-4K超高清","CCTV 4K","CCTV4K超"],
        "CCTV-8K": ["CCTV8K超高清","CCTV8K","CCTV-8K超高清","CCTV 8K"],
        "CCTV兵器科技": ["CCTV-兵器科技","CCTV兵器科技","兵器科技"],
        "CCTV风云音乐": ["CCTV-风云音乐","CCTV风云音乐","风云音乐"],
        "CCTV第一剧场": ["CCTV-第一剧场","CCTV第一剧场","第一剧场"],
        "CCTV风云足球": ["CCTV-风云足球","CCTV风云足球","风云足球"],
        "CCTV风云剧场": ["CCTV-风云剧场","CCTV风云剧场","风云剧场"],
        "CCTV怀旧剧场": ["CCTV-怀旧剧场","CCTV怀旧剧场","怀旧剧场"],
        "CCTV女性时尚": ["CCTV-女性时尚","CCTV女性时尚","女性时尚"],
        "CCTV世界地理": ["CCTV-世界地理","CCTV世界地理","世界地理"],
        "CCTV央视台球": ["CCTV-央视台球","CCTV央视台球","央视台球"],
        "CCTV高尔夫·网球": ["CCTV-高尔夫网球","CCTV高尔夫网球","CCTV央视高网","CCTV-高尔夫·网球","央视高网","高尔夫网球"],
        "CCTV央视文化精品": ["CCTV-央视文化精品","CCTV央视文化精品","CCTV文化精品","CCTV-文化精品","文化精品","央视文化精品"],
        "CCTV卫生健康": ["CCTV-卫生健康","CCTV卫生健康","卫生健康"],
        "CCTV电视指南": ["CCTV-电视指南","CCTV电视指南","电视指南"],
        "中国教育1台": ["CETV1","中国教育一台","中国教育1","CETV-1 综合教育","CETV-1"],
        "中国教育2台": ["CETV2","中国教育二台","中国教育2","CETV-2 空中课堂","CETV-2"],
        "中国教育3台": ["CETV3","中国教育三台","中国教育3","CETV-3 教育服务","CETV-3"],
        "中国教育4台": ["CETV4","中国教育四台","中国教育4","CETV-4 职业教育","CETV-4"],
        "早期教育": ["中国教育5台","中国教育5","中国教育五台","CETV早期教育","早期教育","CETV 早期教育","CETV-5","CETV5"],
        "CGTN": ["CGTN英语","CGTN-英语"],
        "CGTN-纪录": ["CGTN纪录","CGTN-纪录","CGTN记录","CGTN记录片"],
        "CGTN-西班牙语": ["CGTN-西班牙语","CGTN西班牙语","CGTN西语"],
        "CGTN-法语": ["CGTN-法语","CGTN法语"],
        "CGTN-俄语": ["CGTN-俄语","CGTN俄语"],
        "CGTN-阿拉伯语": ["CGTN-阿拉伯语","CGTN阿拉伯语"],
        "湖南卫视4K": ["湖南卫视4K"],
        "北京卫视4K": ["北京卫视4K","北京卫视4K超高清","北京卫视4K超"],
        "东方卫视4K": ["东方卫视4K"],
        "广东卫视4K": ["广东卫视4K"],
        "深圳卫视4K": ["深圳卫视4K"],
        "山东卫视4K": ["山东卫视4K"],
        "四川卫视4K": ["四川卫视4K"],
        "浙江卫视4K": ["浙江卫视4K"],
        "山东卫视": ["山东卫视"],
        "北京卫视": ["北京卫视"],
        "东方卫视": ["东方卫视"],
        "重庆卫视": ["重庆卫视"],
        "江苏卫视": ["江苏卫视"],
        "浙江卫视": ["浙江卫视"],
        "江西卫视": ["江西卫视"],
        "安徽卫视": ["安徽卫视"],
        "湖南卫视": ["湖南卫视"],
        "湖北卫视": ["湖北卫视"],
        "河南卫视": ["河南卫视"],
        "河北卫视": ["河北卫视"],
        "广东卫视": ["广东卫视"],
        "广西卫视": ["广西卫视"],
        "深圳卫视": ["深圳卫视"],
        "大湾区卫视": ["大湾区卫视"],
        "东南卫视": ["东南卫视"],
        "海南卫视": ["海南卫视"],
        "四川卫视": ["四川卫视"],
        "贵州卫视": ["贵州卫视"],
        "云南卫视": ["云南卫视"],
        "天津卫视": ["天津卫视"],
        "辽宁卫视": ["辽宁卫视"],
        "黑龙江卫视": ["黑龙江卫视"],
        "吉林卫视": ["吉林卫视"],
        "内蒙古卫视": ["内蒙古卫视"],
        "宁夏卫视": ["宁夏卫视"],
        "山西卫视": ["山西卫视"],
        "陕西卫视": ["陕西卫视"],
        "甘肃卫视": ["甘肃卫视"],
        "青海卫视": ["青海卫视"],
        "西藏卫视": ["西藏卫视"],
        "三沙卫视": ["三沙卫视","海南三沙卫视"],
        "兵团卫视": ["兵团卫视","新疆兵团卫视"],
        "延边卫视": ["延边卫视","吉林延边卫视"],
        "海峡卫视": ["海峡卫视","福建海峡卫视"],
        "农林卫视": ["农林卫视","陕西农林卫视"],
        "安多卫视": ["安多卫视","青海安多卫视"],
        "康巴卫视": ["康巴卫视","四川康巴卫视"],
        "西藏卫视藏语": ["西藏卫视（藏语）","西藏卫视藏语","西藏藏语频道"],
        "安多卫视藏语": ["安多藏语综合"],
        "康巴卫视藏语": ["康巴藏语综合"],
        "内蒙古卫视蒙语": ["内蒙古卫视（蒙语）"],
        "山东教育卫视": ["山东教育", "教育卫视"],
        "CHC影迷电影": ["CHC高清电影", "CHC-影迷电影", "影迷电影", "chc高清电影"],
        "CHC动作电影": ["CHC动作电影","CHC-动作电影"],
        "CHC家庭影院": ["CHC家庭影院","CHC-家庭影院"],
        "星空卫视": ["星空卫视", "星空衛视", "星空衛視"],
        "CHANNEL[V]": ["CHANNEL-V", "Channel[V]"],
        "凤凰卫视": ["凤凰卫视中文台", "凤凰中文", "凤凰卫视中文", "凤凰卫视"],
        "凤凰资讯": ["凤凰卫视资讯台", "凤凰资讯", "凤凰卫资讯"],
        "凤凰香港": ["凤凰香港台", "凤凰卫视香港", "凤凰香港"],
        "凤凰电影": ["凤凰电影", "凤凰电影台", "凤凰卫视电影", "凤凰卫视电影台", " 凤凰电影"],
        "北京IPTV4K超清": ["IPTV淘4K", "北京IPTV4K超清", "北京淘4K", "淘4K", "淘 4K"],
        "北京IPTV淘电影": ["IPTV淘电影", "淘电影", "北京淘电影"],
        "北京IPTV淘精彩": ["IPTV淘精彩", "淘精彩", "北京淘精彩"],
        "北京IPTV淘剧场": ["IPTV淘剧场", "淘剧场", "北京淘剧场"],
        "北京IPTV淘娱乐": ["IPTV淘娱乐", "淘娱乐", "北京淘娱乐"],
        "北京IPTV淘BABY": ["IPTV淘BABY", "淘BABY", "北京淘BABY", "IPTV淘baby", "北京IPTV淘baby", "北京淘baby"],
        "北京IPTV萌宠TV": ["IPTV淘萌宠", "北京IPTV萌宠TV", "北京淘萌宠","淘萌宠"],
        "北京卡酷少儿": ["卡酷少儿", "北京卡酷少儿", "卡酷动画","北京KAKU少儿","BRTV卡酷少儿"],
        "北京纪实科教": ["纪实科教", "北京纪实科教", "BRTV纪实科教", "纪实科教8K"],
        "朝阳区": ["朝阳融媒"],
        "通州区": ["通州融媒"],
        "房山区": ["房山电视台"],
        "密云区": ["密云电视台"],
        "延庆区": ["延庆电视台"],
        "广东岭南戏曲": ["岭南戏曲", "广东岭南戏曲"],
        "广东现代教育": ["现代教育", "广东现代教育"],
        "广东南方购物": ["南方购物", "广东南方购物"],
        "惠州综合频道": ["HZTV-1", "惠州综合频道"],
        "惠州公共频道": ["HZTV-2", "惠州公共频道"],
        "广东嘉佳卡通": ["嘉佳卡通", "广东嘉佳卡通"],
        "江苏优漫卡通": ["优漫卡通", "江苏优漫卡通"],
        "湖南金鹰纪实": ["金鹰纪实", "湖南金鹰纪实"],
        "湖南金鹰卡通": ["金鹰卡通","湖南金鹰卡通"],
        "湖南快乐垂钓": ["快乐垂钓","湖南快乐垂钓"],
        "湖南茶频道": ["茶频道","湖南茶频道"],
        "湖南先锋乒羽": ["先锋乒羽","湖南先锋乒羽"],
        "上海新闻综合": ["新闻综合"],
        "上海都市频道": ["都市频道"],
        "上海东方影视": ["东方影视"],
        "上海教育频道": ["上海教育"],
        "上海第一财经": ["第一财经", "上海第一财经"],
        "上海动漫秀场": ["动漫秀场", "上海动漫秀场"],
        "上海动漫秀场4K": ["动漫秀场4K"],
        "上海都市剧场": ["都市剧场", "上海都市剧场"],
        "上海都市剧场4K": ["都市剧场4K"],
        "上海东方财经": ["东方财经", "上海东方财经"],
        "上海法治天地": ["法治天地", "上海法治天地"],
        "上海游戏风云": ["游戏风云", "上海游戏风云"],
        "上海生活时尚": ["生活时尚", "上海生活时尚"],
        "上海金色学堂": ["金色学堂", "上海金色学堂"],
        "上海乐游频道": ["乐游","乐游频道", "上海乐游","上海乐游纪实"],
        "上海欢笑剧场": ["欢笑剧场", "上海欢笑剧场"],
        "上海欢笑剧场4K": ["欢笑剧场4K", "上海欢笑剧场4K"],
        "上海哈哈炫动": ["哈哈炫动","炫动卡通", "上海哈哈炫动"],
        "河南梨园频道": ["梨园","河南梨园频道"],
        "河南文物宝库": ["文物宝库","河南文物宝库"],
        "河南武术世界": ["武术世界","河南武术世界"],
        "河北农民": ["河北三农频道"],
        "魅力足球": ["魅力足球"],
        "天元围棋": ["天元围棋"],
        "中国天气": ["中国天气"],
        "中国交通": ["中国交通","中国交通频道"],
        "睛彩青少": ["睛彩羽毛球"],
        "睛彩竞技": ["睛彩竞技"],
        "睛彩篮球": ["睛彩篮球"],
        "睛彩广场舞": ["睛彩广场舞"],
        "求索纪录": ["求索记录"],
        "求索纪录4K": ["求索纪录4K", "求索记录4K", "求索纪录 4K", "求索记录 4K"],
        "成都综合频道": ["CDTV1综合"],
        "成都经济频道": ["CDTV2经济"],
        "成都生活频道": ["CDTV3生活"],
        "成都影视频道": ["CDTV4影视"],
        "成都公共频道": ["CDTV5公共"],
        "成都少儿频道": ["CDTV6少儿"],
        "黄河电视台": ["山西黄河频道"],
        "山西影视": ["山西影视频道"],
        "XJTV-1": ["新疆卫视"],
        "XJTV-2": ["新疆卫视2"],
        "XJTV-3": ["新疆卫视3"],
        "XJTV-4": ["新疆卫视4"],
        "XJTV-5": ["新疆卫视5"],
        "XJTV-6": ["新疆卫视6"],
        "XJTV-7": ["新疆卫视10"],
        "XJTV-8": ["新疆卫视12"],
        "海南公共频道": ["海南公共"],
        "海南少儿频道": ["海南少儿"],
        "海南文旅频道": ["海南文旅"],
        "海南新闻频道": ["海南新闻"],
        "海南自贸频道": ["海南自贸"],
        "海口1台": ["海口1"],
        "三亚1台": ["三亚1"],
        "澄迈TV": ["澄迈"],
        "贵州公共频道": ["贵州卫视2"],
        "贵州影视文艺": ["贵州卫视3"],
        "贵州大众生活": ["贵州卫视4"],
        "贵州法制频道": ["贵州卫视5"],
        "贵州科教健康": ["贵州卫视6"],
        "贵州经济频道": ["贵州卫视7"],
        "重庆新闻频道": ["重庆新闻频道"],
        "重庆影视剧频道": ["重庆影视剧频道"],
        "重庆社会与法": ["重庆社会与法"],
        "重庆红岩文化": ["重庆红岩文化","重庆时红岩文化"],
        "重庆文体娱乐": ["重庆文体娱乐"],
        "重庆新农村": ["重庆新农村","重庆新农村频道"],
        "重庆融媒": ["重广融媒"],
        "重庆少儿频道": ["重庆少儿频道"],
        "重庆红叶频道": ["重庆红叶频道"],
        "重庆汽摩频道": ["汽摩","汽摩频道","重庆汽摩","重庆汽摩频道"],
        "重庆移动频道": ["重庆移动频道"],
        "开州综合": ["开州综合"]
    }
    
    return CATEGORY_MAPPING, CHANNEL_NAME_MAPPING

def normalize_channel_name(channel_name, channel_name_mapping):
    """标准化频道名称 - 精确匹配别名"""
    channel_name = channel_name.strip()
    
    # 精确匹配：查找频道名称是否在映射的别名中
    for standard_name, aliases in channel_name_mapping.items():
        if channel_name in aliases:
            return standard_name
    
    # 如果没有找到匹配，返回原名称
    return channel_name

def classify_channels(valid_groups, category_mapping, channel_name_mapping):
    """对频道进行分类 - 使用完整的频道分类规则"""
    classified_channels = {category: [] for category in category_mapping.keys()}
    
    print("开始频道重分类...")
    
    # 从有效分组生成频道列表
    channel_lines = []
    for group_name, channels in valid_groups.items():
        for channel_name, channel_url in channels:
            # 在播放地址后加入$所属组名
            channel_line = f"{channel_name},{channel_url}${group_name}"
            channel_lines.append(channel_line)
    
    print(f"共处理 {len(channel_lines)} 个频道")
    
    # 构建反向映射，便于快速查找
    reverse_category_map = {}
    for category, channels_in_category in category_mapping.items():
        for channel in channels_in_category:
            reverse_category_map[channel] = category
    
    # 构建别名到标准名称的映射
    alias_to_standard = {}
    for standard_name, aliases in channel_name_mapping.items():
        for alias in aliases:
            alias_to_standard[alias] = standard_name
    
    for line in channel_lines:
        line = line.strip()
        if not line:
            continue
            
        # 解析频道名称和完整信息
        if ',' in line:
            parts = line.split(',', 1)
            if len(parts) == 2:
                channel_name, rest = parts
                
                # 1. 首先检查频道名称是否直接匹配分类中的标准名称
                found_category = reverse_category_map.get(channel_name.strip())
                
                # 2. 如果没有直接匹配，使用频道名称映射规则标准化频道名称
                if not found_category:
                    normalized_name = normalize_channel_name(channel_name, channel_name_mapping)
                    found_category = reverse_category_map.get(normalized_name)
                
                # 3. 如果还没找到分类，放入"其他频道"
                if not found_category:
                    found_category = "其他频道,#genre#"
                
                # 将完整的行添加到对应分类
                classified_channels[found_category].append(line)
    
    # 统计各分类的频道数量
    for category, channels in classified_channels.items():
        print(f"分类 '{category}' 有 {len(channels)} 个频道")
    
    return classified_channels

def get_beijing_time():
    """获取北京时间（不使用pytz）"""
    # 获取UTC时间
    utc_now = datetime.utcnow()
    # 转换为北京时间（UTC+8）
    beijing_time = utc_now + timedelta(hours=8)
    return beijing_time.strftime('%Y-%m-%d %H:%M:%S')

def generate_reclassify_file(classified_channels, output_file):
    """生成reclassify.txt文件"""
    print(f"生成 {output_file}...")
    
    # 获取北京时间
    beijing_time = get_beijing_time()
    
    output_lines = [f"# 生成时间: {beijing_time} (北京时间)"]
    
    # 按照固定顺序输出分类
    category_order = [
        "央视频道,#genre#",
        "付费频道,#genre#", 
        "卫视频道,#genre#",
        "国际频道,#genre#",
        "北京频道,#genre#",
        "上海频道,#genre#",
        "天津频道,#genre#",
        "重庆频道,#genre#",
        "广东频道,#genre#",
        "山东频道,#genre#",
        "江苏频道,#genre#",
        "浙江频道,#genre#",
        "安徽频道,#genre#",
        "福建频道,#genre#",
        "江西频道,#genre#",
        "河南频道,#genre#",
        "湖北频道,#genre#",
        "湖南频道,#genre#",
        "河北频道,#genre#",
        "山西频道,#genre#",
        "内蒙古频道,#genre#",
        "辽宁频道,#genre#",
        "吉林频道,#genre#",
        "黑龙江频道,#genre#",
        "广西频道,#genre#",
        "海南频道,#genre#",
        "四川频道,#genre#",
        "贵州频道,#genre#",
        "云南频道,#genre#",
        "陕西频道,#genre#",
        "甘肃频道,#genre#",
        "青海频道,#genre#",
        "宁夏频道,#genre#",
        "新疆频道,#genre#",
        "其他频道,#genre#"
    ]
    
    for category in category_order:
        if category in classified_channels and classified_channels[category]:
            output_lines.append("")  # 空行分隔
            output_lines.append(category)  # 分类标题
            output_lines.extend(classified_channels[category])
    
    # 写入文件
    with open(output_file, 'w', encoding='utf-8') as f:
        f.write('\n'.join(output_lines))
    
    total_channels = sum(len(channels) for channels in classified_channels.values())
    print(f"生成完成！总频道数: {total_channels}")
    return total_channels

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
        
        print("步骤5: 加载频道分类映射...")
        category_mapping, channel_name_mapping = load_category_mapping()
        
        print("步骤6: 重分类频道生成reclassify.txt...")
        classified_channels = classify_channels(valid_groups, category_mapping, channel_name_mapping)
        total_channels = generate_reclassify_file(classified_channels, 'reclassify.txt')
        
        end_time = time.time()
        processing_time = end_time - start_time
        
        print(f"=== 完成！ ===")
        print(f"处理时间: {processing_time:.2f} 秒")
        print(f"有效分组: {len(valid_groups)} 个")
        print(f"总频道数: {total_channels} 个")
        print(f"生成文件: reclassify.txt")
        
    except Exception as e:
        print(f"错误: {e}")
        import traceback
        traceback.print_exc()
        exit(1)

if __name__ == "__main__":
    main()
