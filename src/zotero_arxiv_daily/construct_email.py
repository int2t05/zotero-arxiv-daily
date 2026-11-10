import html
import math

from .protocol import Paper, PaperOverview


framework = """
<!DOCTYPE HTML>
<html>
<head>
  <style>
    .star-wrapper {
      font-size: 1.3em;
      line-height: 1;
      display: inline-flex;
      align-items: center; /* 保持对齐 */
    }
    .half-star {
      display: inline-block;
      width: 0.5em;
      overflow: hidden;
      white-space: nowrap;
      vertical-align: middle;
    }
    .full-star {
      vertical-align: middle;
    }
  </style>
</head>
<body>

<div>
    __CONTENT__
</div>

<br><br>
<div>
To unsubscribe, remove your email in your Github Action setting.
</div>

</body>
</html>
"""

def get_empty_html():
  """生成当日无论文时的提示卡片。"""
  block_template = """
  <table border="0" cellpadding="0" cellspacing="0" width="100%" style="font-family: Arial, sans-serif; border: 1px solid #ddd; border-radius: 8px; padding: 16px; background-color: #f9f9f9;">
  <tr>
    <td style="font-size: 20px; font-weight: bold; color: #333;">
        今日没有匹配论文
    </td>
  </tr>
  </table>
  """
  return block_template

def _overview_html(overview: PaperOverview | None, has_code_link: bool) -> str:
    """渲染论文速览；仅对检测到代码链接的论文显示复现线索。"""
    if overview is None:
        return "<p><strong>论文速览：</strong>暂未生成，请查看原始摘要和原文。</p>"

    fields = [
        ("研究问题", overview.research_problem),
        ("方法", overview.method),
        ("结果与证据", overview.evidence),
        ("方向关联", overview.interest_fit),
    ]
    if has_code_link:
        note = overview.reproduction_notes or "论文文本未提供复现细节；需打开代码仓库核对。"
        fields.append(("代码复现线索", note))
    return "".join(
        f"<p><strong>{html.escape(label)}：</strong>{html.escape(' '.join(value.split()))}</p>"
        for label, value in fields
    )


def get_block_html(
    title: str,
    authors: str,
    rate: str,
    overview: PaperOverview | None,
    pdf_url: str,
    affiliations: str | None = None,
    code_url: str | None = None,
):
    """生成单篇论文卡片，并转义远程文本和链接。"""
    overview_html = _overview_html(overview, has_code_link=bool(code_url))
    links = []
    if pdf_url:
        links.append(
            f'<a href="{html.escape(pdf_url, quote=True)}" style="display:inline-block;text-decoration:none;font-size:14px;font-weight:bold;color:#fff;background:#d9534f;padding:8px 16px;border-radius:4px;">PDF</a>'
        )
    if code_url:
        links.append(
            f'<a href="{html.escape(code_url, quote=True)}" style="display:inline-block;text-decoration:none;font-size:14px;font-weight:bold;color:#fff;background:#555;padding:8px 16px;border-radius:4px;">代码仓库</a>'
        )
    block_template = """
    <table border="0" cellpadding="0" cellspacing="0" width="100%" style="font-family: Arial, sans-serif; border: 1px solid #ddd; border-radius: 8px; padding: 16px; background-color: #f9f9f9;">
    <tr>
        <td style="font-size: 20px; font-weight: bold; color: #333;">
            {title}
        </td>
    </tr>
    <tr>
        <td style="font-size: 14px; color: #666; padding: 8px 0;">
            {authors}
            <br>
            <i>{affiliations}</i>
        </td>
    </tr>
    <tr>
        <td style="font-size: 14px; color: #333; padding: 8px 0;">
            <strong>相似度：</strong> {rate}
        </td>
    </tr>
    <tr>
        <td style="font-size: 14px; line-height: 1.6; color: #333; padding: 8px 0;">
            {overview_html}
        </td>
    </tr>

    <tr>
        <td style="padding: 8px 0;">
            {links}
        </td>
    </tr>
</table>
"""
    return block_template.format(
        title=html.escape(title),
        authors=html.escape(authors),
        rate=html.escape(str(rate)),
        overview_html=overview_html,
        affiliations=html.escape(affiliations or "Unknown Affiliation"),
        links=" ".join(links),
    )

def get_stars(score:float):
    """将相似度映射为邮件中的星级显示。"""
    full_star = '<span class="full-star">⭐</span>'
    half_star = '<span class="half-star">⭐</span>'
    low = 6
    high = 8
    if score <= low:
        return ''
    elif score >= high:
        return full_star * 5
    else:
        interval = (high-low) / 10
        star_num = math.ceil((score-low) / interval)
        full_star_num = int(star_num/2)
        half_star_num = star_num - full_star_num * 2
        return '<div class="star-wrapper">'+full_star * full_star_num + half_star * half_star_num + '</div>'


def render_email(papers:list[Paper]) -> str:
    """将速览卡片组装为 HTML 邮件正文。"""
    parts = []
    if len(papers) == 0 :
        return framework.replace('__CONTENT__', get_empty_html())
    
    for p in papers:
        #rate = get_stars(p.score)
        rate = round(p.score, 1) if p.score is not None else 'Unknown'
        author_list = [a for a in p.authors]
        num_authors = len(author_list)
        if num_authors <= 5:
            authors = ', '.join(author_list)
        else:
            authors = ', '.join(author_list[:3] + ['...'] + author_list[-2:])
        if p.affiliations is not None:
            affiliations = p.affiliations[:5]
            affiliations = ', '.join(affiliations)
            if len(p.affiliations) > 5:
                affiliations += ', ...'
        else:
            affiliations = 'Unknown Affiliation'
        parts.append(
            get_block_html(
                p.title,
                authors,
                rate,
                p.overview,
                p.pdf_url,
                affiliations,
                p.code_url,
            )
        )

    content = '<br>' + '</br><br>'.join(parts) + '</br>'
    return framework.replace('__CONTENT__', content)
