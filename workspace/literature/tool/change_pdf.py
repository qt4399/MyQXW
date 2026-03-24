from pdf2image import convert_from_path, convert_from_bytes
import requests
import os
import tempfile

def pdf_url_to_images(pdf_url, save_dir="pdf2img", dpi=300, fmt="png"):
    """
    直接从PDF网页URL转换为图片
    :param pdf_url: arXiv PDF的网页链接（如https://arxiv.org/pdf/2504.09138v1.pdf）
    :param save_dir: 图片保存目录
    :param dpi: 图片分辨率（300dpi为高清）
    :param fmt: 图片格式（png/jpg）
    :return: 转换后的图片路径列表
    """
    # 1. 创建保存目录
    if not os.path.exists(save_dir):
        os.makedirs(save_dir)
    
    try:
        # 2. 下载远程PDF（添加请求头，避免被反爬）
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        }
        print(f"正在下载PDF: {pdf_url}")
        response = requests.get(pdf_url, headers=headers, timeout=30)
        response.raise_for_status()  # 检查请求是否成功
        
        # 3. 将PDF字节数据转换为图片（核心：无需落地文件）
        print(f"开始转换PDF为{fmt}格式（{dpi}dpi）...")
        pages = convert_from_bytes(
            response.content,  # 直接使用内存中的PDF字节数据
            dpi=dpi,
            fmt=fmt,
            # 可选：指定poppler路径（Windows用户需配置，Mac/Linux无需）
            # poppler_path=r"C:\poppler-23.11.0\Library\bin"
        )
        
        # 4. 保存图片（按页码命名）
        saved_paths = []
        for i, page in enumerate(pages):
            img_name = f"page_{i+1}.{fmt}"
            img_path = os.path.join(save_dir, img_name)
            page.save(img_path, fmt=fmt)
            saved_paths.append(img_path)
            print(f"已保存：{img_path}")
        
        print(f"\n转换完成！共{len(pages)}页，图片保存在 {os.path.abspath(save_dir)}")
        return saved_paths
    
    except requests.exceptions.RequestException as e:
        print(f"下载PDF失败：{e}")
        return []
    except Exception as e:
        print(f"转换图片失败：{e}")
        return []

# ==================== 调用示例 ====================
if __name__ == "__main__":
    # 替换为你要转换的arXiv PDF链接
    pdf_url = "https://arxiv.org/pdf/2504.09138v1.pdf"
    
    # 调用函数（可自定义保存目录、分辨率、格式）
    pdf_url_to_images(
        pdf_url=pdf_url,
        save_dir="arxiv_images",  # 图片保存目录
        dpi=300,                  # 高清分辨率
        fmt="png"                 # 无损格式
    )
