import feedparser
import urllib.parse  # 用于URL编码
import urllib.request  # 用于设置请求头
from datetime import datetime  # 格式化时间

# 配置请求头（模拟浏览器，避免被arxiv拒绝）
headers = {
    'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
}
# 创建请求处理器，添加请求头
opener = urllib.request.build_opener()
opener.addheaders = [(k, v) for k, v in headers.items()]
urllib.request.install_opener(opener)

def search_arxiv_papers(keyword, max_results=10):
    """
    搜索arxiv论文，支持带空格的关键词，返回标题、编号、PDF链接、摘要、发布时间
    :param keyword: 搜索关键词（如"attention is"）
    :param max_results: 返回结果数量
    :return: 论文列表（含完整信息）
    """
    # 核心修复：对关键词做URL编码，处理空格/特殊字符
    encoded_keyword = urllib.parse.quote(keyword)
    # 拼接合法的API URL
    api_url = f"https://export.arxiv.org/api/query?search_query=all:{encoded_keyword}&start=0&max_results={max_results}"
    
    try:
        # 解析API响应
        feed = feedparser.parse(api_url)
        if not feed.entries:
            print("未找到相关论文！")
            return []
        
        papers = []
        for entry in feed.entries:
            title = entry.title
            arxiv_id = entry.id.split('/')[-1]
            pdf_link = f"https://arxiv.org/pdf/{arxiv_id}.pdf"
            summary = entry.summary.strip()
            publish_time = datetime.strptime(entry.published, '%Y-%m-%dT%H:%M:%SZ').strftime('%Y-%m-%d')
            update_time = datetime.strptime(entry.updated, '%Y-%m-%dT%H:%M:%SZ').strftime('%Y-%m-%d')
            
            paper_info = {
                "title": title,
                "arxiv_id": arxiv_id,
                "pdf_link": pdf_link,
                "summary": summary,
                "publish_time": publish_time,
                "update_time": update_time
            }
            papers.append(paper_info)
        
        return papers
    except Exception as e:
        print(f"搜索失败：{str(e)}")
        return []

# 主程序
if __name__ == "__main__":
    # 获取用户输入的关键词（支持带空格）
    keyword = input("请输入搜索标题：")
    # 调用搜索函数（max_results=1000可按需调整，arXiv API单次建议不超过1000）
    result=search_arxiv_papers(keyword, max_results=10)
    print(len(result))
