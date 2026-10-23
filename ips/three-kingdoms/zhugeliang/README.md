# 诸葛亮 | Zhuge Liang

![Zhuge Liang](docs/assets/zhugeliang-hero.png)

Zhuge Liang (181–234), courtesy name Kongming, was a statesman and military strategist of the Shu Han period.

## 简介 / Overview

He is celebrated for his wisdom, dedication, and leadership, and remains one of the most influential figures in Three Kingdoms history and Chinese literature.

## 知识范围 / Knowledge Scope

- **历史 / History：** 史实记载（如《三国志》）
- **文学 / Literature：** 文学演绎（如《三国演义》）
- **文化 / Culture：** 民俗、信仰、艺术等
- **原创 / Original：** 本项目原创内容

> 本主题严格区分史实、文学演绎与原创内容。

## 角色素材 / Character Artwork

Part of the **LVRAG Three Kingdoms Character Series**.

## 项目状态 / Status

早期研发阶段。具体功能与发布时间以后续正式发布为准。

## 联系与归属 / Contact

项目组织：[LongerVisionCanada](https://github.com/LongerVisionCanada)

## 许可与素材 / License

软件许可、知识内容授权与形象素材使用条款尚待确定。在正式公布许可之前，不应推定本仓库内容已获得任何特定开源许可或商业再利用授权。

## Engineering status — October 2026

- **Knowledge:** 10 human-reviewed, source-attributed atomic records from the historical source workflow.
- **Source handling:** Chen Shou main text and Pei Songzhi annotations remain distinguishable, including variant accounts.
- **Retrieval:** Local EmbeddingGemma indexing uses 768-dimensional vectors.
- **Validation:** 8/8 conservative retrieval tests passed; the universal runtime passed dual-agent HTTP tests.
- **Release:** ZhugeLiang Preview R2 includes an audited correction to the evidence limitation for ZGL-ATOM-0010.
- **Cloud:** Release assets passed SHA256 verification on the Guangzhou host; separate new cloud containers have not yet been deployed.
- **Privacy:** Private knowledge sources, embeddings, and deployment configuration are not published.

The release uses Universal LVRAG v0.2, with per-agent knowledge and retrieval policies. Successful topic retrieval is not proof that every detail of a question is historically established.
