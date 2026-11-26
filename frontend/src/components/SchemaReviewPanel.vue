<template>
  <section
    class="review-panel"
    data-testid="schema-review-panel"
    data-module="schema_review_pack"
  >
    <header class="review-head">
      <div>
        <h3>结构复核包 · 跨班交接入口</h3>
        <p class="review-desc">
          交班人挑选可疑原始行并导出复核包，服务端冻结下载时的样本字节、字段位置与分隔规则版本；
          接班人回填判读，核验通过后可直接发起字段解析。复核包仅限载明的文件、批次与原始行范围。
        </p>
      </div>
      <div class="review-head-actions">
        <a
          class="btn primary"
          data-testid="quick-download-a8"
          :href="downloadPackUrl(STORY_PACK)"
          download
        >下载结构复核包（首次导出：ID 表头 + A8 首条数据）</a>
        <button
          class="btn"
          type="button"
          data-testid="advance-story"
          :disabled="storyBusy"
          @click="onAdvanceStory"
        >{{ storyBusy ? '推进中…' : '接收迟到补段并让新分隔规则生效' }}</button>
      </div>
    </header>

    <p v-if="storyMessage" class="story-message" data-testid="story-message">{{ storyMessage }}</p>

    <div class="review-grid">
      <!-- 左栏：复核包列表 + 新增导出 -->
      <div class="review-col">
        <div class="card">
          <h4>已寄出的结构复核包</h4>
          <ul class="pack-list" data-testid="pack-list">
            <li v-for="pack in packs" :key="String(pack.id)" class="pack-item">
              <button
                type="button"
                class="pack-main"
                :data-testid="`pack-${pack['复核包编号']}`"
                :class="{ active: selectedNo === pack['复核包编号'] }"
                @click="openPack(String(pack['复核包编号']))"
              >
                <span class="pack-no">{{ pack['复核包编号'] }}</span>
                <span class="pack-meta">{{ pack['关联批次'] }} · {{ pack['覆盖范围'] }} 行 · {{ pack.status }}</span>
              </button>
              <span class="pack-item-actions">
                <a
                  class="link"
                  :data-testid="`download-${pack['复核包编号']}`"
                  :href="downloadPackUrl(String(pack['复核包编号']))"
                  download
                >下载</a>
                <button
                  type="button"
                  class="link"
                  :data-testid="`backfill-${pack['复核包编号']}`"
                  @click="openPack(String(pack['复核包编号']), 'backfill')"
                >回填判读</button>
                <button
                  type="button"
                  class="link"
                  :data-testid="`existing-${pack['复核包编号']}`"
                  @click="openExisting(String(pack['复核包编号']))"
                >打开已有判读</button>
              </span>
            </li>
          </ul>
        </div>

        <div class="card">
          <h4>新增 / 导出结构复核包</h4>
          <form data-testid="export-pack-form" class="stack" @submit.prevent="onCreatePack">
            <label><span>复核包编号</span>
              <input v-model="createForm.pack_no" data-testid="new-pack-no" />
            </label>
            <label><span>关联批次（复核包只对该批次有效）</span>
              <input v-model="createForm.intake_batch" data-testid="new-pack-batch" />
            </label>
            <label><span>目标文件</span>
              <input v-model="createForm.file_name" data-testid="new-pack-file" />
            </label>
            <label><span>分隔规则编号（冻结其版本）</span>
              <input v-model="createForm.rule_no" data-testid="new-pack-rule" />
            </label>
            <label><span>样本原始行（原样冻结，首行 ID 表头、次行 A8 首条数据）</span>
              <textarea
                v-model="createForm.sample_lines_text"
                rows="4"
                data-testid="new-pack-lines"
              ></textarea>
            </label>
            <label><span>可疑原始行号（逗号分隔）</span>
              <input v-model="createForm.suspicious_rows_text" data-testid="new-pack-selected" />
            </label>
            <button class="btn primary" type="submit" data-testid="export-pack-submit" :disabled="creating">
              {{ creating ? '生成中…' : '挑选可疑原始行并导出复核包' }}
            </button>
            <a
              v-if="createdDownloadUrl"
              class="created-download"
              data-testid="created-pack-download"
              :href="createdDownloadUrl"
              download
            >⬇ 下载刚生成的复核包（样本字节与规则版本已冻结）</a>
            <p v-if="createError" class="error-text" data-testid="create-error">{{ createError }}</p>
          </form>
        </div>
      </div>

      <!-- 右栏：详情 / 回填页 -->
      <div class="review-col wide" v-if="detail">
        <div class="card" data-testid="pack-detail">
          <div class="detail-head">
            <h4>
              回填页 · {{ detail.pack['复核包编号'] }}
              <span class="status-tag" :data-status="detail.pack.status">{{ detail.pack.status }}</span>
            </h4>
            <RouterLink
              class="link"
              :to="`/review-backfill/${encodeURIComponent(String(detail.pack['复核包编号']))}`"
              data-testid="open-standalone-backfill"
            >在独立回填页打开 ↗</RouterLink>
          </div>
          <dl class="meta-grid">
            <div><dt>关联批次</dt><dd data-testid="detail-batch">{{ detail.pack['关联批次'] }}</dd></div>
            <div><dt>目标文件</dt><dd>{{ detail.pack['目标文件'] }}</dd></div>
            <div><dt>覆盖原始行</dt><dd>{{ detail.pack['覆盖起始行'] }}–{{ detail.pack['覆盖结束行'] }}（目标文件起始行 {{ detail.pack['目标文件起始行'] }}，不可更改）</dd></div>
            <div><dt>可疑原始行号</dt><dd>{{ detail.pack['可疑原始行号'] }}</dd></div>
            <div><dt>导出时规则版本</dt><dd data-testid="frozen-rule-version">{{ detail.pack['分隔规则版本'] }}</dd></div>
            <div><dt>快照令牌</dt><dd class="mono">{{ detail.pack.snapshot_token }}</dd></div>
          </dl>
          <div class="download-row">
            <a class="btn primary" :href="downloadPackUrl(no)" download data-testid="download-review-pack">下载结构复核包（JSON 原件）</a>
            <a class="btn" :href="downloadPackUrl(no, 'csv')" download data-testid="download-review-pack-csv">下载导出样本字节（CSV）</a>
            <button class="btn" type="button" data-testid="open-evidence" @click="onOpenEvidence">查看实际首条字段与原行证据</button>
            <button class="btn" type="button" data-testid="open-cross-batch" @click="onOpenCrossBatch">查看异批拒绝记录</button>
          </div>

          <div class="two-samples">
            <!-- 初次见到的字段位置 -->
            <div class="sample-box frozen" data-testid="frozen-positions">
              <h5>① 初次见到的字段位置（导出时冻结）</h5>
              <table class="mini-table">
                <thead><tr><th>位置</th><th>字段</th></tr></thead>
                <tbody>
                  <tr v-for="pos in detail.pack['字段位置'] || []" :key="pos['位置'] ?? pos.index">
                    <td>{{ pos['位置'] ?? pos.index }}</td>
                    <td data-testid="frozen-field-name">{{ pos['字段'] ?? pos.field }}</td>
                  </tr>
                </tbody>
              </table>
              <pre class="raw-pre" data-testid="frozen-sample">{{ detail.pack['样本原文'] }}</pre>
              <p class="hint">第一次导出即包含 ID 表头与 A8 首条数据；样本字节保持原样。</p>
            </div>

            <!-- 后来到达的样本片段 -->
            <div class="sample-box current" data-testid="current-sample">
              <h5>② 后来到达的样本片段（补段 / 新规则后的当前样本）</h5>
              <button class="btn ghost" type="button" data-testid="refresh-current" @click="onRefreshCurrent()">刷新当前样本与令牌</button>
              <div v-if="current">
                <p v-if="current.different_first_data" class="warn-text" data-testid="different-first">
                  注意：拿补段另开新包会读到不同的第一条数据
                  「{{ current.new_pack_first_data }}」，而旧包首条是「{{ current.frozen_first_data }}」。
                </p>
                <p><strong>迟到补段：</strong></p>
                <pre class="raw-pre" data-testid="late-fragment">{{ current.late_fragment?.join('\n') || '（补段尚未到达，可点击顶部「接收迟到补段」）' }}</pre>
                <p><strong>当前文件全部原始行：</strong></p>
                <pre class="raw-pre">{{ current.all_lines?.join('\n') }}</pre>
                <p class="hint">当前生效规则：{{ current.rule?.rule_no }} / {{ current.rule?.rule_version }}</p>
              </div>
              <p v-else class="hint">尚未刷新。</p>
            </div>
          </div>

          <!-- 已有判读 -->
          <div
            v-if="showJudgment && (detail.judgment || openedAttempt)"
            class="judgment-card"
            data-testid="existing-judgment-panel"
          >
            <h5>已有判读（可重新打开核对）</h5>
            <dl class="meta-grid">
              <div><dt>判读编号</dt><dd>{{ shownJudgment['判读编号'] }}</dd></div>
              <div><dt>状态</dt><dd :data-status="shownJudgment.status">{{ shownJudgment.status }}</dd></div>
              <div><dt>判读人</dt><dd>{{ shownJudgment['判读人'] }}</dd></div>
              <div><dt>首行是否表头</dt><dd>{{ shownJudgment['首行是否表头'] }}</dd></div>
              <div><dt>确认起始行</dt><dd data-testid="judgment-start-row">{{ shownJudgment['确认起始行'] ?? shownJudgment['获准起始行'] }}</dd></div>
              <div><dt>实际首条字段</dt><dd data-testid="judgment-first-field"><strong>{{ shownJudgment['实际首条字段'] }}</strong></dd></div>
              <div class="wide-dd"><dt>原行证据（原始行 {{ shownJudgment['证据原始行号'] }}）</dt>
                <dd class="mono" data-testid="judgment-raw-evidence">{{ shownJudgment['原行证据'] }}</dd></div>
              <div v-if="shownJudgment['拒绝原因']" class="wide-dd"><dt>拒绝原因</dt>
                <dd class="error-text">{{ shownJudgment['拒绝原因'] }}</dd></div>
            </dl>
          </div>

          <!-- 回填表单 -->
          <form class="backfill-form" data-testid="backfill-form" @submit.prevent="onSubmit()">
            <h5>回填判读表单（判断与导出时看到的字段位置对应）</h5>
            <div class="form-grid">
              <label><span>接班人 / 判读人</span>
                <input v-model="form.reviewer" data-testid="judge-reviewer" placeholder="reviewer-yi" />
              </label>
              <label><span>提交目标批次（改成他批将触发异批拒绝）</span>
                <input v-model="form.batch" data-testid="judge-batch" />
              </label>
              <label><span>实际首条字段</span>
                <input v-model="form.actual_first_field" data-testid="judge-first-field" />
              </label>
              <label><span>确认解析起始行</span>
                <input v-model.number="form.start_row" type="number" min="1" data-testid="judge-start-row" />
              </label>
              <label><span>证据原始行号</span>
                <input v-model.number="form.evidence_line" type="number" min="1" data-testid="judge-evidence-line" />
              </label>
              <label><span>首行是否表头</span>
                <select v-model="headerChoice" data-testid="judge-is-header">
                  <option value="yes">是表头（起始行 2）</option>
                  <option value="no">不是表头（起始行 1）</option>
                </select>
              </label>
              <label class="wide-dd"><span>样本令牌（过期会收到「过期拒绝」）</span>
                <input v-model="form.seen_token" class="mono" data-testid="judge-token" />
              </label>
              <label><span>提交依据</span>
                <select v-model="form.target" data-testid="judge-target">
                  <option value="pack">返回原包：按冻结字段位置回填</option>
                  <option value="current">继续处理当前样本：按刷新后的令牌</option>
                </select>
              </label>
            </div>
            <div class="submit-row">
              <button class="btn primary" type="submit" data-testid="submit-judgment" :disabled="submitting">
                {{ submitting ? '核验提交中…' : '核验并提交判读' }}
              </button>
              <button class="btn" type="button" data-testid="duplicate-submit" @click="onDuplicate">同包重复提交一次（验证唯一有效登记）</button>
              <button class="btn" type="button" data-testid="cross-batch-submit" @click="onCrossBatch">拿到另一批回填一次</button>
              <button class="btn ghost" type="button" data-testid="stale-submit" @click="onStaleSubmit">模拟过期令牌提交</button>
              <button class="btn ghost" type="button" data-testid="range-submit" @click="onRangeSubmit">模拟范围拒绝提交</button>
            </div>

            <div
              v-if="feedback"
              class="feedback"
              :class="feedback.ok ? 'ok' : 'err'"
              data-testid="submit-feedback"
              :data-category="feedback.category"
            >
              <strong>{{ feedback.ok ? '已受理' : '被拒绝' }}（{{ categoryLabel(feedback.category) }}）：</strong>
              <span data-testid="feedback-message">{{ feedback.message }}</span>
              <div v-if="!feedback.ok && (feedback.category === 'stale' || feedback.category === 'out_of_range')" class="recovery-row">
                <button type="button" class="btn primary" data-testid="back-to-original-pack" @click="onBackToPack">返回原包</button>
                <button type="button" class="btn" data-testid="continue-current-sample" @click="onContinueCurrent">继续处理当前样本</button>
              </div>
            </div>
          </form>

          <!-- 发起解析 -->
          <div class="parse-bar">
            <button
              class="btn primary"
              type="button"
              data-testid="parse-with-judgment"
              :disabled="parsing"
              @click="onParse"
            >{{ parsing ? '解析中…' : '发起字段解析（消费复核包有效起始行）' }}</button>
            <span class="hint">字段解析按当前获准起始行写出，采用结论同步批次台账，解析行号可反查样本。</span>
          </div>
          <div v-if="parseResult" class="parse-result" data-testid="parse-result">
            <h5>解析采用结果</h5>
            <p>
              判读 <strong>{{ parseResult.judgment_no }}</strong> ·
              获准起始行 <strong data-testid="parse-start-row">{{ parseResult.approved_start_row }}</strong> ·
              实际首条字段 <strong data-testid="parse-first-field">{{ parseResult.first_field }}</strong> ·
              首条数据值 <strong>{{ parseResult.first_data_value }}</strong>
            </p>
            <p>写出的原始行号：<code data-testid="parse-line-numbers">{{ JSON.stringify(parseResult.parsed_line_numbers) }}</code></p>
            <p>批次台账：<code data-testid="parse-ledger">{{ parseResult.ledger_batch_no }}</code>
              <span v-if="parseResult.idempotent" class="hint">（该判读已采用，本次为幂等返回，不重复写出）</span></p>
          </div>
        </div>
      </div>

      <div v-else-if="!loading" class="review-col wide">
        <div class="card empty-hint" data-testid="no-pack-selected">
          请选择左侧复核包，打开回填页；也可以先下载包含 ID 表头与 A8 首条数据的结构复核包。
        </div>
      </div>
    </div>

    <!-- 实际首条字段 + 原行证据弹层 -->
    <div v-if="showEvidence" class="modal-backdrop" data-testid="evidence-dialog" @click.self="showEvidence = false">
      <div class="modal wide-modal" role="dialog" aria-label="实际首条字段与原行证据">
        <h3>实际首条字段 · 原行证据</h3>
        <div v-if="evidence" class="evidence-body">
          <p>关联批次：{{ evidence.batch }} ｜ 原始行号：{{ evidence['原始行号'] }}</p>
          <p class="first-field-line">实际首条字段：
            <strong data-testid="first-field-view">{{ evidence['实际首条字段'] }}</strong>
          </p>
          <p>原行证据：</p>
          <pre class="raw-pre big" data-testid="raw-evidence-view">{{ evidence.raw_line }}</pre>
          <template v-if="evidence.judgment">
            <p>采用判读：{{ evidence.judgment['判读编号'] }}（{{ evidence.judgment['复核包编号'] }}）</p>
          </template>
          <template v-if="evidence.field_parse_trace">
            <p>字段解析痕迹：解析编号 {{ evidence.field_parse_trace['解析编号'] }}，
              回挂判读 {{ evidence.field_parse_trace['判读编号'] }}</p>
          </template>
        </div>
        <p v-else class="hint">该批次/行号暂未找到证据。</p>
        <div class="page-actions"><button class="btn primary" type="button" @click="showEvidence = false">关闭</button></div>
      </div>
    </div>

    <!-- 异批拒绝弹层 -->
    <div v-if="showCrossBatch" class="modal-backdrop" data-testid="cross-batch-dialog" @click.self="showCrossBatch = false">
      <div class="modal wide-modal" role="dialog" aria-label="异批拒绝记录">
        <h3>异批拒绝记录（借用他批结果属于越权）</h3>
        <ul class="cross-list" data-testid="cross-batch-list">
          <li v-for="item in crossBatchItems" :key="String(item.id)" data-testid="cross-batch-item">
            <strong>{{ item['复核包编号'] }}</strong>
            ｜提交批次 {{ item['关联批次'] }} → 包属批次 {{ item['包属批次'] }}
            <p class="error-text">{{ item['拒绝原因'] }}</p>
          </li>
          <li v-if="!crossBatchItems.length" class="hint">暂无异批拒绝记录。</li>
        </ul>
        <div class="page-actions"><button class="btn primary" type="button" @click="showCrossBatch = false">关闭</button></div>
      </div>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { RouterLink } from 'vue-router'

import {
  advanceStory,
  createReviewPack,
  downloadPackUrl,
  fetchCrossBatchRejections,
  fetchEvidence,
  fetchPackDetail,
  fetchPackList,
  parsePack,
  refreshCurrent,
  submitJudgment,
  STORY_PACK_FALLBACK,
  type AnyRecord,
} from '@/api/review-pack'

const props = withDefaults(defineProps<{ initialPack?: string; backfillOnly?: boolean }>(), {
  initialPack: '',
  backfillOnly: false,
})

const STORY_PACK = STORY_PACK_FALLBACK
const OTHER_BATCH = 'FI-20260906002'

const packs = ref<AnyRecord[]>([])
const selectedNo = ref('')
const detail = ref<AnyRecord | null>(null)
const loading = ref(false)
const submitting = ref(false)
const parsing = ref(false)
const creating = ref(false)
const storyBusy = ref(false)
const storyMessage = ref('')
const createError = ref('')
const createdDownloadUrl = ref('')
const showJudgment = ref(false)
const openedAttempt = ref<AnyRecord | null>(null)
const showEvidence = ref(false)
const evidence = ref<AnyRecord | null>(null)
const showCrossBatch = ref(false)
const crossBatchItems = ref<AnyRecord[]>([])

const feedback = ref<{ ok: boolean; message: string; category: string } | null>(null)
const parseResult = ref<AnyRecord | null>(null)

const createForm = reactive({
  pack_no: 'SRP-WEB-A8',
  intake_batch: 'FI-20260906001',
  file_name: 'A8-head-late-segment.csv',
  rule_no: 'DR-001',
  sample_lines_text: 'ID,label,measure,occurred_at\nA8,alpha-8,12.50,2026-09-01 08:00:00\nA9,alpha-9,13.25,2026-09-01 08:10:00',
  suspicious_rows_text: '2',
})

const form = reactive({
  reviewer: 'reviewer-yi',
  batch: '',
  actual_first_field: 'ID',
  start_row: 2,
  evidence_line: 2,
  seen_token: '',
  target: 'pack',
})
const headerChoice = ref<'yes' | 'no'>('yes')

const no = computed(() => String(detail.value?.pack?.['复核包编号'] ?? selectedNo.value))
const current = computed<AnyRecord | null>(() => detail.value?.current_sample ?? null)
const shownJudgment = computed<AnyRecord>(
  () => detail.value?.judgment ?? openedAttempt.value ?? {},
)

function categorize(message: string): string {
  if (message.includes('异批') || message.includes('越权')) return 'cross_batch'
  if (message.includes('过期')) return 'stale'
  if (message.includes('范围')) return 'out_of_range'
  if (message.includes('重复') || message.includes('一次有效')) return 'duplicate'
  if (message.includes('核验未通过') || message.includes('不一致')) return 'verify_failed'
  return 'accepted'
}

function categoryLabel(category: string): string {
  return {
    cross_batch: '异批/越权',
    stale: '过期',
    out_of_range: '范围',
    duplicate: '重复登记',
    verify_failed: '核验失败',
    accepted: '受理',
  }[category] ?? category
}

async function loadPacks(selectNo?: string) {
  const payload = await fetchPackList()
  packs.value = payload.items ?? []
  const target = selectNo ?? props.initialPack ?? selectedNo.value
  if (target && packs.value.some((p) => String(p['复核包编号']) === target)) {
    await openPack(target)
  } else if (!selectedNo.value && packs.value.length) {
    const preferred = packs.value.find((p) => String(p['复核包编号']) === STORY_PACK) ?? packs.value[0]
    await openPack(String(preferred['复核包编号']))
  }
}

async function openPack(packNo: string, action?: string, preserveFeedback = false) {
  selectedNo.value = packNo
  loading.value = true
  if (!preserveFeedback) feedback.value = null
  parseResult.value = null
  openedAttempt.value = null
  try {
    detail.value = await fetchPackDetail(packNo)
    const pack = detail.value.pack ?? detail.value
    form.batch = String(pack['关联批次'] ?? '')
    form.actual_first_field = String(pack['字段位置']?.[0]?.['字段'] ?? 'ID')
    form.start_row = 2
    const selected = pack['可疑行列表'] ?? []
    form.evidence_line = selected[0] ? Number(selected[0]) : 2
    form.seen_token = String(pack.snapshot_token ?? '')
    form.target = 'pack'
    headerChoice.value = 'yes'
    showJudgment.value = Boolean(detail.value.judgment)
    if (action === 'backfill') {
      setTimeout(() => {
        document.querySelector<HTMLElement>('[data-testid="backfill-form"]')?.scrollIntoView({ behavior: 'smooth', block: 'center' })
      }, 50)
    }
  } finally {
    loading.value = false
  }
}

async function openExisting(packNo: string) {
  await openPack(packNo)
  showJudgment.value = true
  if (!detail.value?.judgment) {
    // 后端 open_existing_judgment 已包含最近一次被拒绝的登记，detail.judgments 里取最后一条。
    const attempts: AnyRecord[] = detail.value?.judgments ?? []
    openedAttempt.value = attempts.length ? attempts[attempts.length - 1] : null
    if (!openedAttempt.value) {
      feedback.value = { ok: false, category: 'none', message: '该复核包还没有任何判读登记。' }
    }
  }
}

async function onAdvanceStory() {
  storyBusy.value = true
  try {
    const result = await advanceStory()
    storyMessage.value = result.message ?? '补段与新规则已就绪'
    await loadPacks(no.value || STORY_PACK)
    if (selectedNo.value) await onRefreshCurrent(true)
  } finally {
    storyBusy.value = false
  }
}

async function onCreatePack() {
  creating.value = true
  createError.value = ''
  createdDownloadUrl.value = ''
  try {
    const sample_lines = createForm.sample_lines_text.split('\n')
    const suspicious_rows = createForm.suspicious_rows_text
      .split(',')
      .map((s) => Number(s.trim()))
      .filter((n) => !Number.isNaN(n))
    const result = await createReviewPack({
      pack_no: createForm.pack_no,
      intake_batch: createForm.intake_batch,
      file_name: createForm.file_name,
      rule_no: createForm.rule_no,
      sample_lines,
      suspicious_rows,
      export_time: new Date().toISOString(),
    })
    if (!result.ok) {
      createError.value = result.message ?? '复核包生成失败'
      return
    }
    const packNo = String(result.entry?.['复核包编号'] ?? createForm.pack_no)
    createdDownloadUrl.value = downloadPackUrl(packNo)
    await loadPacks(packNo)
  } catch (error) {
    createError.value = error instanceof Error ? error.message : '复核包生成失败'
  } finally {
    creating.value = false
  }
}

function buildSubmitBody(overrides: AnyRecord = {}) {
  return {
    reviewer: form.reviewer,
    batch: form.batch,
    actual_first_field: form.actual_first_field,
    first_row_is_header: headerChoice.value === 'yes',
    start_row: form.start_row,
    evidence_line: form.evidence_line,
    seen_token: form.seen_token,
    target: form.target,
    ...overrides,
  }
}

async function runSubmit(overrides: AnyRecord = {}) {
  if (!no.value) return
  submitting.value = true
  try {
    const result = await submitJudgment(no.value, buildSubmitBody(overrides))
    const nextFeedback = {
      ok: result.ok,
      message: result.message ?? '',
      category: result.ok ? 'accepted' : categorize(result.message ?? ''),
    }
    // 重新拉取详情但保留本次提交反馈，避免反馈被切换包的重置逻辑清掉。
    await openPack(no.value, undefined, true)
    feedback.value = nextFeedback
    if (overrides.batch && String(overrides.batch) !== String(detail.value?.pack?.['关联批次'])) {
      await loadCrossBatch()
    }
    return result
  } finally {
    submitting.value = false
  }
}

function onSubmit() {
  return runSubmit()
}

function onDuplicate() {
  // 同包重复提交：恢复本包批次与正确令牌后再发一次，服务端必须拒绝第二次有效登记。
  const owner = String(detail.value?.pack?.['关联批次'] ?? '')
  form.batch = owner
  form.seen_token = String(detail.value?.pack?.snapshot_token ?? form.seen_token)
  form.target = 'pack'
  return runSubmit({ batch: owner })
}

async function onCrossBatch() {
  await loadCrossBatch()
  const owner = String(detail.value?.pack?.['关联批次'] ?? '')
  const other = owner === OTHER_BATCH ? 'FI-20260906009' : OTHER_BATCH
  await runSubmit({ batch: other })
  form.batch = owner
  showCrossBatch.value = true
  await loadCrossBatch()
}

function onStaleSubmit() {
  return runSubmit({ seen_token: 'snap-EXPIRED-TOKEN' })
}

function onRangeSubmit() {
  return runSubmit({ evidence_line: 999, start_row: 999 })
}

function onBackToPack() {
  form.target = 'pack'
  form.seen_token = String(detail.value?.pack?.snapshot_token ?? '')
  feedback.value = { ok: true, category: 'accepted', message: '已返回原包冻结视图：请按初次见到的字段位置核对后重新提交。' }
  document.querySelector<HTMLElement>('[data-testid="frozen-positions"]')?.scrollIntoView({ behavior: 'smooth' })
}

async function onContinueCurrent() {
  form.target = 'current'
  const result = await refreshCurrent(no.value)
  const token = result.entry?.token ?? result.entry?.[2]?.token
  if (token) form.seen_token = String(token)
  await openPack(no.value)
  // openPack 会把 token 重置为冻结令牌，这里再次覆盖成当前样本令牌。
  form.target = 'current'
  const refreshed = await refreshCurrent(no.value)
  form.seen_token = String((refreshed as AnyRecord).entry?.token ?? token ?? '')
  feedback.value = { ok: true, category: 'accepted', message: '已切换到当前样本并刷新令牌，可在核对补段后继续判读。' }
}

async function onRefreshCurrent(silent = false) {
  const result = await refreshCurrent(no.value)
  if (!silent && result.ok) storyMessage.value = result.message ?? '当前样本已刷新'
  await openPack(no.value)
}

async function onParse() {
  if (!no.value) return
  parsing.value = true
  try {
    const result = await parsePack(no.value)
    if (!result.ok) {
      feedback.value = {
        ok: false,
        category: categorize(result.message ?? ''),
        message: result.message ?? '解析被拒绝',
      }
      return
    }
    const parsedEntry = result.entry ?? null
    const message = result.message ?? '字段解析已完成'
    await loadPacks(no.value)
    parseResult.value = parsedEntry
    feedback.value = { ok: true, category: 'accepted', message }
  } finally {
    parsing.value = false
  }
}

async function onOpenEvidence() {
  if (!no.value) return
  const lineNo = form.evidence_line || detail.value?.pack?.['可疑行列表']?.[0] || 2
  const result = await fetchEvidence(no.value, Number(lineNo))
  evidence.value = result.entry ?? null
  showEvidence.value = true
}

async function loadCrossBatch() {
  const payload = await fetchCrossBatchRejections()
  crossBatchItems.value = payload.items ?? []
}

async function onOpenCrossBatch() {
  await loadCrossBatch()
  showCrossBatch.value = true
}

defineExpose({
  openPack,
  openExisting,
  refresh: () => loadPacks(),
})

onMounted(async () => {
  await loadPacks()
  await loadCrossBatch()
})
</script>

<style scoped>
.review-panel { background: #f8fafc; border: 1px solid var(--border); border-radius: 12px; padding: 14px 16px; margin: 10px 0 16px; }
.review-head { display: flex; justify-content: space-between; gap: 16px; align-items: flex-start; flex-wrap: wrap; }
.review-head h3 { margin: 0 0 4px; }
.review-desc { color: var(--muted); font-size: 12.5px; max-width: 760px; margin: 0; line-height: 1.6; }
.review-head-actions { display: flex; flex-direction: column; gap: 8px; align-items: stretch; }
.story-message { background: #ecfdf3; border: 1px solid #abefc6; color: #067647; padding: 6px 10px; border-radius: 6px; font-size: 13px; }
.review-grid { display: grid; grid-template-columns: 340px 1fr; gap: 14px; margin-top: 12px; }
.review-col { display: flex; flex-direction: column; gap: 14px; min-width: 0; }
.card { background: #fff; border: 1px solid var(--border); border-radius: 10px; padding: 12px 14px; }
.card h4 { margin: 0 0 10px; }
.pack-list { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 8px; }
.pack-item { border: 1px solid var(--border); border-radius: 8px; padding: 8px; display: flex; flex-direction: column; gap: 6px; }
.pack-main { text-align: left; background: none; border: none; cursor: pointer; display: flex; flex-direction: column; gap: 2px; }
.pack-main.active .pack-no { color: var(--brand); }
.pack-no { font-weight: 700; font-size: 13px; }
.pack-meta { font-size: 12px; color: var(--muted); }
.pack-item-actions { display: flex; gap: 10px; flex-wrap: wrap; }
.stack { display: flex; flex-direction: column; gap: 8px; }
.stack label span, .backfill-form label span { display: block; font-size: 12px; color: var(--muted); margin-bottom: 3px; }
.stack input, .stack textarea, .form-grid input, .form-grid select { width: 100%; border: 1px solid var(--border); border-radius: 6px; padding: 7px 8px; font-size: 13px; box-sizing: border-box; }
.created-download { color: #067647; font-size: 13px; font-weight: 600; }
.detail-head { display: flex; justify-content: space-between; align-items: center; }
.status-tag { font-size: 12px; border: 1px solid var(--border); border-radius: 999px; padding: 1px 10px; margin-left: 8px; }
.meta-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 8px 14px; margin: 8px 0; }
.meta-grid dt { font-size: 12px; color: var(--muted); }
.meta-grid dd { margin: 2px 0 0; font-size: 13px; }
.wide-dd { grid-column: 1 / -1; }
.mono { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 12px; word-break: break-all; }
.download-row, .submit-row, .parse-bar { display: flex; gap: 10px; align-items: center; flex-wrap: wrap; margin: 10px 0; }
.two-samples { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; margin: 12px 0; }
.sample-box { border: 1px solid var(--border); border-radius: 8px; padding: 10px; min-width: 0; }
.sample-box.frozen { background: #f0f7ff; }
.sample-box.current { background: #fff8eb; }
.sample-box h5, .backfill-form h5, .parse-result h5 { margin: 0 0 8px; }
.mini-table { width: 100%; border-collapse: collapse; margin-bottom: 8px; }
.mini-table th, .mini-table td { border: 1px solid var(--border); padding: 3px 8px; font-size: 12.5px; text-align: left; }
.raw-pre { background: #0f172a; color: #e2e8f0; padding: 8px 10px; border-radius: 6px; font-size: 12px; overflow-x: auto; white-space: pre-wrap; margin: 0; }
.raw-pre.big { font-size: 13px; padding: 12px; }
.hint { font-size: 12px; color: var(--muted); margin: 6px 0 0; }
.warn-text { color: #b54708; background: #fffaeb; border: 1px solid #fedf89; padding: 6px 8px; border-radius: 6px; font-size: 12.5px; }
.judgment-card { border: 1px solid #abefc6; background: #f6fef9; border-radius: 8px; padding: 10px 12px; margin: 10px 0; }
.backfill-form { border-top: 1px dashed var(--border); padding-top: 10px; margin-top: 10px; }
.form-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 10px 12px; }
.feedback { border-radius: 8px; padding: 8px 12px; font-size: 13px; margin-top: 10px; }
.feedback.ok { background: #ecfdf3; border: 1px solid #abefc6; color: #067647; }
.feedback.err { background: #fef3f2; border: 1px solid #fda29b; color: #b42318; }
.recovery-row { display: flex; gap: 10px; margin-top: 8px; }
.parse-result { background: #eef4ff; border: 1px solid #b2ccff; border-radius: 8px; padding: 8px 12px; font-size: 13px; }
.parse-result code { background: #fff; padding: 1px 6px; border-radius: 4px; }
.empty-hint { color: var(--muted); }
.wide-modal { width: min(760px, 100%); }
.evidence-body .first-field-line { font-size: 15px; }
.cross-list { padding-left: 0; list-style: none; display: flex; flex-direction: column; gap: 10px; max-height: 50vh; overflow: auto; }
.cross-list li { border: 1px solid #fda29b; background: #fef3f2; border-radius: 8px; padding: 8px 10px; font-size: 13px; }
@media (max-width: 1100px) { .review-grid { grid-template-columns: 1fr; } .two-samples, .form-grid, .meta-grid { grid-template-columns: 1fr; } }
</style>
