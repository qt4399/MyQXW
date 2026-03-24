import sys
from pathlib import Path
from tool.change_pdf import pdf_url_to_images
sys.path.append(str(Path(__file__).resolve().parents[2]))

from workspace.literature.store import read_index

index_data = read_index()
papers = index_data.get("papers", {})

for paper in papers.values():
    pdf_url = str(paper.get("pdf_url", "")).strip()
    if pdf_url:
        pdf_url_to_images(
        pdf_url=pdf_url,
        save_dir="arxiv_images",  # 图片保存目录
        dpi=300,                  # 高清分辨率
        fmt="png"                 # 无损格式
    )
