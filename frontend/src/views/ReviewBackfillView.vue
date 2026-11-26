<template>
  <section class="backfill-page" data-testid="standalone-backfill-page">
    <header class="backfill-head">
      <div>
        <h2>结构复核回填页</h2>
        <p class="page-desc">
          左侧为初次导出时冻结的字段位置，右侧为后来到达的样本片段；可打开已有判读，
          收到过期或范围拒绝时可返回原包或继续处理当前样本。
        </p>
      </div>
      <RouterLink class="btn" to="/schema_sniff">返回结构嗅探页</RouterLink>
    </header>
    <SchemaReviewPanel :initial-pack="packNo" :backfill-only="true" />
  </section>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { useRoute } from 'vue-router'

import SchemaReviewPanel from '@/components/SchemaReviewPanel.vue'

const route = useRoute()
const packNo = computed(() => String(route.params.packNo ?? route.query.pack ?? ''))
</script>

<style scoped>
.backfill-head { display: flex; justify-content: space-between; align-items: flex-start; gap: 16px; margin: 12px 0; }
.backfill-head h2 { margin: 0 0 4px; }
</style>
