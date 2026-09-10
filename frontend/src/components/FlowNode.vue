<template>
  <div class="flow-node" :class="{ 'flow-node--branch': node.branch }">
    <div class="flow-node-index" v-if="node.index !== undefined">{{ node.index }}</div>
    <div class="flow-node-body">
      <div class="flow-node-title">{{ node.title }}</div>
      <div v-if="node.sub" class="flow-node-sub">{{ node.sub }}</div>
      <div v-if="node.note" class="flow-node-note">{{ node.note }}</div>
    </div>
  </div>
</template>

<script setup>
defineProps({
  node: { type: Object, required: true },
})
</script>

<style scoped>
.flow-node {
  box-sizing: border-box;
  display: flex;
  align-items: flex-start;
  gap: 10px;
  width: 280px;
  min-height: 56px;
  padding: 12px 14px;
  background: linear-gradient(135deg, #ffffff, #f4f8ff);
  border: 1px solid #d8e6ff;
  border-radius: 12px;
  box-shadow: 0 4px 12px rgba(37, 99, 235, 0.08);
}
.flow-node--branch {
  background: linear-gradient(135deg, #ffffff, #f0fff4);
  border-color: #c6efd6;
  box-shadow: 0 4px 12px rgba(34, 197, 94, 0.08);
}
.flow-node-index {
  flex-shrink: 0;
  display: grid;
  place-items: center;
  width: 24px;
  height: 24px;
  border-radius: 50%;
  background: #2563eb;
  color: #fff;
  font-size: 13px;
  font-weight: 700;
}
.flow-node-body { flex: 1; min-width: 0; }
.flow-node-title {
  font-size: 14px;
  font-weight: 650;
  color: #172033;
  line-height: 20px;
}
.flow-node-sub {
  margin-top: 3px;
  font-size: 12px;
  color: #667085;
  line-height: 17px;
}
.flow-node-note {
  margin-top: 6px;
  font-size: 11px;
  color: #b45309;
  background: #fff7ed;
  border: 1px dashed #fcd9a8;
  border-radius: 6px;
  padding: 3px 6px;
  line-height: 16px;
}
</style>
