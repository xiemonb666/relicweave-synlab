# 最终总方案视觉 QA：第 1–17 页

文档：RelicWeave_V1.47_A12_VesselForge_PGFrag_Closeout.docx  
文档 SHA-256：`9af0efe877115200dd99bbcf8f24f3124e2932245d71795fc00252d08e278436`  
范围：master_v147_render_v3/page-1.png 至 page-17.png（17 页）  
方法：17 张 PNG 均逐张以 `view_image(detail="original")` 打开；未使用拼图或 OCR 替代逐页检查。页图尺寸均为 1547×2002。  
结果：17/17 页已检查，17 页通过，0 个可见版式问题。

逐页查看 PNG 原图，分辨率均为 1547×2002。顶部右侧页眉“RelicWeave V1.47 完整项目方案”连续可见；底部右侧日期为 2026 年 10 月 7 日，页码为当前页 / 204。目录跨页与续表均按完整续段检查；显示界面的视口边界不作为 PNG 边界。

页眉逐页裁切区的原图字节摘要一致；对预览中看似缺页眉/页脚的页面复核了 PNG 实际上缘与最底 2002 像素，页眉及完整日期/页码均在图像内。长标识符的换行保持可读；历史内容密集本身未作为问题。

## 逐页记录

- Page 1: inspected=true; **PASS** — 页面上部标题“缓缓 RelicWeave 项目完整方案”和版本行清楚；中部至下部摘要段落完整，右下页脚日期与“1 / 204”可读。 PNG SHA-256: `C233CB15B01E1D45BFDA42B4D4030B41CDCC85DB6D02D41CD6792F54772C2D5F`
- Page 2: inspected=true; **PASS** — “文档导航”目录从第 1–4 章延续到 A/B/C 项；页底 C10–C12 均完整，右下“2026 年 10 月 7 日 2 / 204”与正文留白清楚。 PNG SHA-256: `0646C14BF0F3B4E22E94365E4E831A0944053ECFC9C32F60392F59A3E092100B`
- Page 3: inspected=true; **PASS** — 目录续页中的 C13–C15、D1–D12、章节 8–12 及附录索引清楚；下方留白与日期/“3 / 204”页脚完整。 PNG SHA-256: `B099542CFA43106CBE507EF038C871BA5298C16958F51170212D9C5373F794C4`
- Page 4: inspected=true; **PASS** — “1 文档体系与现行口径”下角色表、阶段表均显示完整列框和单元格；页面下方 HW-H1 行及页脚未被截断。 PNG SHA-256: `923BF8B6308A382C707E5054EABE39571E9D3DD91848201D3F1E477053127CC6`
- Page 5: inspected=true; **PASS** — 阶段表续页、 “1.2 当前事实台账”表及第 2 章开头正文均可读；页底表格和段落与“5 / 204”页脚分离。 PNG SHA-256: `FA629C9B5E28A43E5D467F50C95E729952B302346871AE45B0CC46A2503167CD`
- Page 6: inspected=true; **PASS** — “2.1 比赛必须实现与论文需要证明”及“2.2 内部指标合同”表格边界完整；末行“有邻片接受覆盖”未被底边截切，页脚清楚。 PNG SHA-256: `B716C4780CE48952DE54FF6F09100B5F5B78CEAAA98855E444970EB07782E55E`
- Page 7: inspected=true; **PASS** — 2.2 续表、2.2.1 公式说明、2.3 止损段落及第 3 章标题/引导句顺接自然；页脚无碰撞。 PNG SHA-256: `DFFF997F996C5A4ACD4C1B78A0B3E8A139FF201E74E7526C91E1AC8FEC92B5AB`
- Page 8: inspected=true; **PASS** — 第 4 章、A1 启动任务表和 A2 重构说明可读；原图下缘的末段完整结束，右下日期及“8 / 204”清楚。 PNG SHA-256: `A73F57CFD93BC109D84FFFEB609C45214E37C15389CF8DF0D59C5D242749D2A6`
- Page 9: inspected=true; **PASS** — A2.1 最小函数合同表与 A3 输入表示表的三列均完整，长标识符换行仍可辨读；页底日期/页码与正文分开。 PNG SHA-256: `A5F11CEA22DEB7D52FB96FB939784BC47FE2CD4FDDC4C7887453F027433B2A63`
- Page 10: inspected=true; **PASS** — A3.1、A4、A4.1–A4.3 标题与说明段落清晰；页底 A4.3 正文完整，未与页脚相撞。 PNG SHA-256: `20A3C79365C1CCA00446DE3B2DAE5454BCEBD2D3DF83A14A02739622DBCCC45E`
- Page 11: inspected=true; **PASS** — A4.4/A4.5 正文、A4.6 四行表及 A4.7 开头可读；原 PNG 下缘末句“再研究门控。”完整，日期/“11 / 204”页脚清楚。 PNG SHA-256: `3D4F5D1E5322E663FDACDFA74377E397D2BD2357128F62421DE158C17317DF1C`
- Page 12: inspected=true; **PASS** — A4.8/A4.9 与 A5 训练表格行列完整；页底 batch/epoch 段落完整结束后才进入日期/“12 / 204”页脚。 PNG SHA-256: `2A831C8E920D7BDAF6081EBB931DD202250F2FB720D94B03D56CEE45C19942BB`
- Page 13: inspected=true; **PASS** — A5.0 标签表及 A5.1 伪代码各行可读，代码标识符换行无截断；页脚完整。 PNG SHA-256: `58E9465BED355E427D692E74AABB4F9CBF2D038BB7A794DB999AC790318DDC3D`
- Page 14: inspected=true; **PASS** — A5.2 配置模板、A5.3 校准段及 A6 循环示例代码完整；页底代码之后保留空隙，日期/页码清楚。 PNG SHA-256: `D7ABF8085B3F2E7001F71136D5717A2E09D835DBFA2F1893FCF0228FDDB48571`
- Page 15: inspected=true; **PASS** — A6 改造表和 A6.1 说明/原则表的长英文单元格虽换行但可读，表格外框完整；底部“Persistent evidence…”行与页脚分离。 PNG SHA-256: `022434149841D0B45AA77F676DCAA878F31C800EDEAF7F8DF7116561691AC29A`
- Page 16: inspected=true; **PASS** — A6.2 外部论文对照表各列及 A6.3 段落/公式清楚；表格行高足够，右下页脚完整。 PNG SHA-256: `E1B5EA9CCCF7735DD0DB459B5B3A0288549F8AA0A001ACA2500FBB28C3ED4D09`
- Page 17: inspected=true; **PASS** — A6.3 续表与 A6.4 几何侧表格各行完整，长机制名按行换行仍可辨读；底部最后一行和日期/“17 / 204”页脚完整。 PNG SHA-256: `AE442DA52E93929A94B8E248E2EB237CBD527BF147E2A52B936FE5EFBA1F467F`

## 结论

未观察到真实乱码、文字重叠、截字、表格裁切、页眉页脚碰撞、孤立标题或不可读路径/hash。跨页目录与续表衔接清楚。

DOCX 原始 SHA-256 在检查开始时与报告写入后均核对为 `9af0efe877115200dd99bbcf8f24f3124e2932245d71795fc00252d08e278436`；检查期间未修改 DOCX。

