import { defineConfig } from 'vitepress'

// 项目级 Pages 部署在 https://int2t05.github.io/zotero-arxiv-daily/ ，base 必须是子路径
export default defineConfig({
  title: '每日 arXiv 精选',
  description: '基于 Zotero 兴趣画像与 LLM 打分的每日论文推送',
  base: '/zotero-arxiv-daily/',
  head: [
    ['link', { rel: 'icon', type: 'image/svg+xml', href: '/zotero-arxiv-daily/favicon.svg' }],
  ],
  themeConfig: {
    nav: [{ text: '首页', link: '/' }],
    sidebar: [
      {
        text: '每日推送',
        items: [{ text: '最新', link: '/' }],
      },
    ],
  },
})
