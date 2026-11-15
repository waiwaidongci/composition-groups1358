# 砺穗生物炭组成比较册

对五个互斥分析相的相对量做闭合、显式乘法零替换和CLR，在Aitchison几何里比较预定义工艺组，并把全局证据交给独立补样。相通道升级按版本迁移：把原“其余相”拆成两个新相时逐样本补录拆分原量，全部核验后整版切换，历史运行仍按旧相依据解释。

砺穗生物炭实验室有15位化学分析员，上游 `lisui-biochar-phase-202611.csv` 包含炭质相、硅酸盐相、碳酸盐相、磷酸盐相及其余相。过去在表格里直接相关百分比、遇到零静默加常数、看到组差就归因工艺，导致闭合约束伪相关、替换假设不可追溯、解释忽略离散度；逐行改列还会让不同研究混用不同相组成。本系统替代组成变换、全局置换与复配补样归档环节，下游由材料负责人批准独立补样，阅读者下载获批CSV。当前全部是独立合成样本，不是实测成分、产量或工艺原因证明。

## 启动

```sh
cp .env.example .env
docker compose config --quiet
docker compose up -d --build
docker compose exec -T backend python -m scripts.seed_demo
```

含中文与空格的目录可启动。前端 http://localhost:18233 ，API文档 http://localhost:19233/docs ，MySQL localhost:17733。恰好frontend/backend/worker/db/redis五服务，均有健康检查；backend/worker等待数据库与Redis，frontend等待backend。Nginx `/api/` 去前缀代理。命名卷分别持久化MySQL、Redis任务队列、backend/worker共享完整结果JSON。

| 角色 | 账号 | 密码 | 典型动作 |
|---|---|---|---|
| admin 材料负责人 | admin@lisui.demo | Lisui2026! | 七页；创建研究、批注、提交、发起/补录/切换相通道迁移、批准/退回补样 |
| analyst 组成研究员 | analyst@lisui.demo | Lisui2026! | 七页；来源核对、发起与补录迁移、配置δ/B、提交运行和补样说明 |
| viewer 补样阅读者 | viewer@lisui.demo | Lisui2026! | 七页只读；查看迁移进度、下载获批完成研究CSV |

JWT角色在后端执行，viewer写入403、analyst审批403、未获批导出403、重复审批409。登录/批注/排队/worker完成/建议与审批留审计。登录IP每分钟最多30次，另有统一错误中间件。请求校验422只返回loc/msg文本，不回显含NaN/Inf的input。部署时修改JWT_SECRET及Compose内MySQL口令。

## 一天的研究剧本

1. 09:00 顾砚登录，核对 `LS-01` 正组成研究：工艺A/B/C各24个独立样本，五个互斥相通道，原相对量并非都合计100。
2. 09:05 打开 `LS-02`，12行含零，其中每组首样本有两个零。零按未检出通道记录，不静默加伪计数。
3. 09:10 查看 `LS-03` 恒定组成边界，SST=0、PERMANOVA未定义，系统拒绝运行。
4. 09:15 为LS-02冻结δ=.001、B199、seed2026，创建“三工艺组成复核”；系统保留原量、闭合份额、替换后份额和CLR。
5. 09:16 独立worker固定各组规模置换标签，保存199个null R²，以R²上尾含并列+1求全局p。
6. 09:20 真实HTTP运行的LS-02得到R²约.02814246、pseudo-F约.99903、p=.435。这份数据未给出强组差证据，仍可为未检出限与δ假设做独立补样。
7. 09:25 写三工艺同规模补样说明，注明仅报告组内距离描述、未正式检验离散度同质、不将组差当工艺原因。
8. 10:00 罗岑批准归档，程禾以阅读者下载 `composition-run-N.csv`，供独立复配补样核对。
9. 10:10 化验仪升级把“其余相”拆成“有机相”与“残余相”；顾砚发起迁移，分批补录各样本拆分原量，二者之和须等于旧“其余相”，其他四相保持原量。
10. 10:40 罗岑核对全部样本确认后整版切换到 v2，v1退役但仍可读；旧运行与已获批CSV仍按v1五个通道解释。

## 相通道版本与迁移

一个研究有多个不可变的相通道版本。v1由原五相建立（`PhaseVersion`，`source_version_id=null`，样本值读 `composition_samples`），每个派生版本自带 `SampleVersionValue` 冻结原量。`PhaseMigration` 记录“把一个通道拆成两个”的草稿，`PhaseSplitEntry` 逐样本保存补录、和值核验状态与原因。`PhaseVersionComponent` 让新旧版本各自保留完整通道表，历史版本可原地重算。

- **拆分不改和**：两个新通道原量之和须等于旧通道原量（纯相对容差1e-9，按两者最大绝对值缩放，不用绝对下限，避免极小的真实拆分被当作0），其余通道逐样本保持原量。缺测、和值不符、负数/NaN/布尔、含非本次拆分通道、源版本缺该通道原量、迁移创建后新增样本缺补录条目，都会列出具体原因并阻止切换。
- **可中断续补**：`POST /phase-migrations/{id}/entries` 按批写入，随时可从任意未确认样本继续；已确认条目再次提交时跳过且不覆盖，返回 `skipped` 原因。修改已确认值需在切换前新建迁移。
- **整版切换**：`POST /phase-migrations/{id}/activate` 仅在全部样本 `confirmed` 时生效；否则409列出阻塞样本与原因。切换在单一事务内写入目标版本的全部样本原量，并将目标置 `active`、源置 `retired`。
- **竞争迁移**：同一研究同时只有一个 `active`。切换以源版本行上的条件更新做原子提交（`status=active → retired`），竞争的迁移在源退役后置 `invalidated` 并写明原因；读取/补录路径也会惰性解析，保证另一版明确失效。
- **并发一致性**：创建研究与切换都先锁研究行再读版本、通道与样本；切换要么在前（新研究冻结新版本），要么在后（新研究冻结旧版本），不会混用。已排队运行保留创建时捕获的完整快照，不随之后切换变化。
- **旧版仍可分析**：`POST /runs` 可指定 `phase_version_id` 对已退役版本重算；已失效版本拒绝。`/studies/{id}/components|samples?version_id=` 读取指定版本。历史运行结果与导出保留其运行时的 `phase_version`。

来源页显示生效版本、版本数、迁移进度（已确认/和值不符/待补录），并可按版本查看通道与原始样本矩阵。`Migrate`（相通道迁移）页发起拆分、逐样本补录、查看失效原因与整版切换。前端七页：组成总览、相份额来源、相通道迁移、替换与置换、组间证据、复配补样、研究留痕。

## 七页与实体

组成总览、相份额来源、相通道迁移、替换与置换、组间证据、复配补样、研究留痕。`CompositionStudy / PhaseVersion / PhaseVersionComponent / SampleVersionValue / PhaseMigration / PhaseSplitEntry / ComponentSpec / CompositionSample / CompositionRun / ResampleNote` 均贯穿表、model、schema、service、route、前端API、store与页面/组件，另有User/Audit。来源数值/成分/组标签只读核对（迁移补录例外），样本批注可写；运行创建时冻结完整快照（含所选版本），后续批注或版本切换不改历史结果。

seed为3研究×3工艺×24样本=216行、15个成分定义，并为每研究建立v1相通道版本。LS-01正组成，LS-02含12行零分量（每组4行），LS-03固定[50,20,15,10,5]恒定边界。LS-02还预置一个进行中的迁移（“其余相拆为有机相与残余相”，前7个样本已确认），用于演示补录中断后继续。固定种子290/291/292生成，五相互斥，其余相为剩余通道，仅解释相对组成。自然键email、study code、(study,sample code)、(study,component code/position)、基线run name；seed只补缺失，不覆盖用户批注/已批准建议。`SEED_DEMO=true`启动执行一次，失败记日志，也可独立重复执行。

MySQL连续标量 `default_delta`、`delta`、`expected_value`、`submitted_sum` 明确 `DOUBLE(asdecimal=False)`，数值向量/SS/null通过JSON保存Python双精度，未用单精度Float列。旧库启动时 `ensure_upgrade_columns` 为 `composition_runs` 补 `phase_version_id` 可空列，`backfill_versions` 为既有研究建v1并回填旧运行指针（旧运行的 `input_snapshot`/`result` 已自带原五相，指针仅便于筛选）。

## 组成几何

原相对量x非负且非全零，先按行闭合为q=x/Σx。实现先除行最大值防止求和溢出；若正值闭合后下溢到0，受控失败。设一行有z个原始零：

```text
零位置：r_j = δ
正位置：r_j = q_j * (1 − zδ)
要求0 < δ < 1/z
没有零：r = q，仅闭合
CLR_j = log(r_j) − mean(log(r))
Aitchison距离 = ||CLR(x) − CLR(y)||₂
```

δ以闭合后比例为单位，不是原量加数，也不自动估计检出限。保留raw/closed/replaced/CLR及零数，零替换可能改变结论。API允许(0,1)并逐行严格检查zδ<1；UI最小步长.0001。每研究固定4–6个不同成分，本题5个；每组至少2个独立样本，2–5组，最多300样本且N×B≤150000。

组CLR均值、原替换份额算术均值、closure(exp(组CLR均值))的Aitchison中心分别保存，界面条带使用后者，不把它当原份额算术均值。

迁移后版本把旧通道列替换为两列新相；闭合、零替换与CLR仍按该版本自身的通道集合计算，故v1与v2的R²不可直接比较——它们回答不同通道划分下的问题。历史运行保留其运行时版本的 `phase_version`，导出CSV含 `phase_version` 列，便于区分依据。

## PERMANOVA与数值边界

在CLR欧氏空间，T=Σ||Z_i−总均值||²，W=Σ组Σ||Z_i−组均值||²，B=T−W，R²=B/T，pseudo-F=(B/(k−1))/(W/(N−k))。总中心相对首行锚定，再按最大中心差缩放计算SS比例，避免用绝对方差阈值误拒可分辨小变化；组内SS与各组汇总使用math.fsum，标签改名不应改变统计量。

- T=0时未定义，拒绝；不把常量组成说成“无差异p=1”。
- W=0且T>0时R²=1、F无界，JSON以F=null/F_status=unbounded表示；置换仍保存有限R²，检验继续。
- F超数值范围时另标numerical_overflow，不伪造有限值或写JSON Infinity。

B199–999次均匀置换标签，组规模保持，固定seed与自然键排序复现。固定N/k自由度下R²与F单调等价，因此null只保存R²，包含完美分离情况。p=(1+#null R²≥观测R²)/(B+1)。当前v2以 `64*eps*max(1,|观测R²|,max|null R²|)` 作声明的机器尺度并列保护，避免数学同一划分被浮点分组汇总顺序漏计；该保护只用于R²比较，不用于SST拒绝。

全局组差也可受组内离散度影响，只给到组CLR质心的平均/最大距离描述，未正式检验离散度同质；独立与零假设下标签可交换是前提。不是工艺因果、性能概率、逐组对照p或事后选择保证。p最小分辨率1/(B+1)，有Monte Carlo波动。

当前算法/指纹版本为 `closure-replacement-clr-permanova-v2`。v1在真实6点夹具的数学并列漏计曾被独立复核发现；v2修复、空卷重跑及原证据详见TESTING，不用历史v1运行冒充最终结果。

## 工程与开发

Vue3.5/Pinia3/VueRouter4/TypeScript5.7/Vite6.4.6；Python3.11/FastAPI0.115/SQLAlchemy2/NumPy2.2/SciPy1.15/PyMySQL1.1；MySQL8/Redis7/Nginx1.27。后端真算所有变换、SS、R²与置换，前端只展示真实结果。

```sh
# backend，先准备MySQL/Redis，设置DATABASE_URL、REDIS_URL
cd backend
python -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
uvicorn src.main:app --reload --port 8000
# 另开终端在backend启动worker；本地需可写/artifacts，建议Compose
python -m src.worker
# 前端从项目根进入frontend，Vite代理/api到localhost:8000
cd ../frontend
npm ci
npm run dev
```

`backend/src/{routes,controllers,services,models,schemas,middlewares,utils,constants,config}` 按来源、相通道版本/迁移、变换、PERMANOVA、运行、审阅和横切拆分；`backend/scripts/seed_demo.py`；migration为可选索引，metadata首次建表，非独立全量DDL；版本相关表由metadata建表，旧库的 `composition_runs.phase_version_id` 由启动时 `ensure_upgrade_columns` 补齐。`frontend/src/{api,stores,types,components/common,hooks,pages,router,utils,constants}` 为Vue应用。

RunSummary跨首页/结果/审阅，GroupProfiles跨首页/结果，CompositionMatrix跨来源/结果，另有StudySelector、PermutationPlot、PhaseMigration(Migrate页内联)及通用DataTable/Notice/StatusBadge。两hooks useResearch/useAction及utils处理公共状态。角色枚举backend/constants/roles与frontend/constants/enums参与鉴权/角色显示，队列状态backend/constants/status与前端RunStatus参与worker/StatusBadge，审阅Literal在backend/schemas/note和model/service/前端ReviewStatus；版本/迁移/条目状态literal在backend/services/phase_service，前端VersionStatus/MigrationStatus/EntryStatus对应显示。

.env含COMPOSE_PROJECT_NAME、FRONTEND_PORT、BACKEND_PORT、DB_PORT、JWT_SECRET、SEED_DEMO，DATABASE_URL/REDIS_URL由Compose定义。源码不含测试截图/日志；关键JSON/CSV、截图与已知差异在同批test-artifacts/gb-0029。当前为单worker研究系统，无来源上传、多worker去重、崩溃恢复或真实设备操作。清理仅本题：`docker compose down -v --remove-orphans`。MIT License。
