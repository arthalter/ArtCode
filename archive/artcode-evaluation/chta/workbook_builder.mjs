import fs from "node:fs/promises";
import path from "node:path";
import { SpreadsheetFile, Workbook } from "@oai/artifact-tool";

const [reportPath, outputPath] = process.argv.slice(2);
const report = JSON.parse(await fs.readFile(reportPath, "utf8"));
const workbook = Workbook.create();

const colors = {
  navy: "#17324D",
  blue: "#2E75B6",
  pale: "#EAF2F8",
  green: "#D9EAD3",
  amber: "#FCE5CD",
  red: "#F4CCCC",
  gray: "#E7E6E6",
  line: "#C9D4DF",
};

function addSheet(name) {
  const sheet = workbook.worksheets.add(name);
  sheet.showGridLines = false;
  return sheet;
}

function title(sheet, range, text) {
  sheet.getRange(range).merge();
  sheet.getRange(range).values = [[text]];
  sheet.getRange(range).format = {
    fill: colors.navy,
    font: { bold: true, color: "#FFFFFF" },
    verticalAlignment: "center",
  };
  sheet.getRange(range).format.rowHeight = 32;
}

function header(range) {
  range.format = {
    fill: colors.blue,
    font: { bold: true, color: "#FFFFFF" },
    wrapText: true,
    verticalAlignment: "center",
    borders: { preset: "inside", style: "thin", color: colors.line },
  };
}

function body(range) {
  range.format = {
    verticalAlignment: "top",
    wrapText: true,
    borders: { preset: "inside", style: "thin", color: colors.line },
  };
}

function statusFill(status) {
  return status === "complete" ? colors.green : status === "blocked" ? colors.red : colors.amber;
}

const experiments = report.experiments || {};
const mcp = experiments.mcp || {};
const permission = experiments.permission || {};
const swebench = experiments.swebench || {};

// 总览
const summary = addSheet("总览");
title(summary, "A1:H1", "chTA · Agent 系统效率与信息保真评测");
summary.getRange("A3:B6").values = [
  ["Run ID", report.run_id || ""],
  ["总体状态", report.status || ""],
  ["清单指纹", report.manifest?.fingerprint || ""],
  ["模型", report.manifest?.model?.name || ""],
];
summary.getRange("A3:A6").format = { fill: colors.pale, font: { bold: true } };
summary.getRange("B4").format.fill = statusFill(report.status);
summary.getRange("A8:D8").values = [["实验", "Baseline", "Candidate", "变化率"]];
header(summary.getRange("A8:D8"));
summary.getRange("A9:A11").values = [["MCP 首轮工具描述 Token"], ["权限审批请求"], ["SWE-bench resolved"]];
summary.getRange("B9:D9").formulas = [[
  "='MCP明细'!B4",
  "='MCP明细'!C4",
  '=IF(B9=0,"",(B9-C9)/B9)',
]];
summary.getRange("B10:D10").formulas = [[
  "='权限事件'!B4",
  "='权限事件'!C4",
  '=IF(B10=0,"",(B10-C10)/B10)',
]];
summary.getRange("B11:C11").formulas = [[
  '=IF(\'SWEbench实例\'!B4="","N/A",\'SWEbench实例\'!B4)',
  '=IF(\'SWEbench实例\'!C4="","N/A",\'SWEbench实例\'!C4)',
]];
summary.getRange("D11").formulas = [['=IF(OR(B11="N/A",C11="N/A"),"N/A",C11-B11)']];
summary.getRange("D9:D11").format.numberFormat = "0.0%";
summary.getRange("A13:D13").values = [["信息保留", "通过探针", "探针总数", "保留率"]];
header(summary.getRange("A13:D13"));
const retentionProfiles = Object.keys(swebench.retention || {});
summary.getRange("A14:A15").values = [[retentionProfiles[0] || "baseline"], [retentionProfiles[1] || "candidate"]];
summary.getRange("B14:D14").formulas = [[
  '=IF(\'保留探针\'!B4="","N/A",\'保留探针\'!B4)',
  '=IF(\'保留探针\'!C4="","N/A",\'保留探针\'!C4)',
  '=IF(OR(B14="N/A",C14="N/A",C14=0),"N/A",B14/C14)',
]];
summary.getRange("B15:D15").formulas = [[
  '=IF(\'保留探针\'!B5="","N/A",\'保留探针\'!B5)',
  '=IF(\'保留探针\'!C5="","N/A",\'保留探针\'!C5)',
  '=IF(OR(B15="N/A",C15="N/A",C15=0),"N/A",B15/C15)',
]];
summary.getRange("D14:D15").format.numberFormat = "0.0%";
summary.getRange("A17:H17").merge();
summary.getRange("A17:H17").values = [["可用于简历（仅在真实 A/B、证据完整且安全门通过时生成）"]];
summary.getRange("A17:H17").format = { fill: colors.pale, font: { bold: true } };
const statements = report.resume_statements?.length ? report.resume_statements : ["N/A：当前没有通过证据门的数字句。"];
statements.forEach((value, index) => {
  const row = summary.getRangeByIndexes(17 + index, 0, 1, 8);
  row.merge();
  row.values = [[value]];
  row.format = { wrapText: true, rowHeight: 36 };
});
summary.freezePanes.freezeRows(1);
summary.getRange("A1:H25").format.columnWidth = 16;
summary.getRange("A1:A25").format.columnWidth = 30;
summary.getRange("B1:H25").format.columnWidth = 18;

// MCP 明细
const mcpSheet = addSheet("MCP明细");
title(mcpSheet, "A1:M1", "MCP eager / lazy A/B 明细");
const eager = mcp.profiles?.eager || {};
const lazy = mcp.profiles?.lazy || {};
mcpSheet.getRange("A3:C6").values = [
  ["指标", "eager", "lazy"],
  ["首轮工具描述 Token 合计", mcp.comparisons?.first_tool_definition_tokens?.baseline ?? null, mcp.comparisons?.first_tool_definition_tokens?.candidate ?? null],
  ["累计工具描述 Token 合计", mcp.comparisons?.cumulative_tool_definition_tokens?.baseline ?? null, mcp.comparisons?.cumulative_tool_definition_tokens?.candidate ?? null],
  ["Provider prompt Token 合计", mcp.comparisons?.provider_prompt_tokens?.baseline ?? null, mcp.comparisons?.provider_prompt_tokens?.candidate ?? null],
];
header(mcpSheet.getRange("A3:C3"));
const mcpHeaders = ["Profile", "Task", "重复", "成功", "首轮工具Token", "累计工具Token", "Prompt Token", "轮次", "工具调用", "检索调用", "MCP调用", "耗时ms", "证据路径"];
mcpSheet.getRange("A8:M8").values = [mcpHeaders];
header(mcpSheet.getRange("A8:M8"));
const mcpAttempts = mcp.attempts || [];
if (mcpAttempts.length) {
  const rows = mcpAttempts.map((item) => [
    item.profile, item.task_id, item.repetition, item.success,
    item.metrics?.first_tool_definition_tokens ?? null,
    item.metrics?.cumulative_tool_definition_tokens ?? null,
    item.metrics?.provider_prompt_tokens ?? null,
    item.metrics?.model_turns ?? null,
    item.metrics?.tool_calls ?? null,
    item.metrics?.search_calls ?? null,
    item.metrics?.mcp_tool_calls ?? null,
    item.metrics?.duration_ms ?? null,
    item.evidence_path || "",
  ]);
  mcpSheet.getRangeByIndexes(8, 0, rows.length, mcpHeaders.length).values = rows;
  body(mcpSheet.getRangeByIndexes(8, 0, rows.length, mcpHeaders.length));
}
mcpSheet.freezePanes.freezeRows(8);
const mcpLastRow = Math.max(9, 8 + mcpAttempts.length);
mcpSheet.getRange(`A1:M${mcpLastRow}`).format.columnWidth = 15;
mcpSheet.getRange(`B1:B${mcpLastRow}`).format.columnWidth = 28;
mcpSheet.getRange(`M1:M${mcpLastRow}`).format.columnWidth = 48;

// 权限事件
const permSheet = addSheet("权限事件");
title(permSheet, "A1:L1", "权限 once / always 固定回放");
const once = permission.baseline || {};
const always = permission.candidate || {};
permSheet.getRange("A3:C12").values = [
  ["指标", "once", "always"],
  ["审批请求", once.approval_requests ?? null, always.approval_requests ?? null],
  ["正常操作", once.normal_operation_count ?? null, always.normal_operation_count ?? null],
  ["已完成操作", once.completed_operations ?? null, always.completed_operations ?? null],
  ["ALLOW_ONCE", once.allow_once ?? null, always.allow_once ?? null],
  ["ALLOW_ALWAYS", once.allow_always ?? null, always.allow_always ?? null],
  ["规则写入", once.rule_writes ?? null, always.rule_writes ?? null],
  ["规则命中", once.rule_hits ?? null, always.rule_hits ?? null],
  ["误放行", once.false_allows ?? null, always.false_allows ?? null],
  ["误拒绝", once.false_denials ?? null, always.false_denials ?? null],
];
header(permSheet.getRange("A3:C3"));
permSheet.getRange("E3:F5").values = [
  ["派生指标", "值"],
  ["审批降幅", permission.approval_reduction_rate ?? null],
  ["安全门", once.false_allows === 0 && always.false_allows === 0 ? "通过" : "失败"],
];
header(permSheet.getRange("E3:F3"));
permSheet.getRange("F4").format.numberFormat = "0.0%";
permSheet.getRange("E7:F9").values = [
  ["证据", "路径"],
  ["once", once.evidence_path || ""],
  ["always", always.evidence_path || ""],
];
header(permSheet.getRange("E7:F7"));
permSheet.getRange("F8:F9").format = { wrapText: true };
permSheet.getRange("A1:L12").format.columnWidth = 18;
permSheet.getRange("A1:A12").format.columnWidth = 24;
permSheet.getRange("F1:F12").format.columnWidth = 54;

// SWE-bench 实例
const sweSheet = addSheet("SWEbench实例");
title(sweSheet, "A1:G1", "SWE-bench-Live 官方实例结果");
const sweProfiles = Object.keys(swebench.profiles || {});
const p0 = swebench.profiles?.[sweProfiles[0]] || {};
const p1 = swebench.profiles?.[sweProfiles[1]] || {};
sweSheet.getRange("A3:C6").values = [
  ["指标", sweProfiles[0] || "baseline", sweProfiles[1] || "candidate"],
  ["Resolved", p0.resolved ?? null, p1.resolved ?? null],
  ["Gold-valid", p0.gold_valid ?? null, p1.gold_valid ?? null],
  ["Resolve rate", p0.resolve_rate ?? null, p1.resolve_rate ?? null],
];
header(sweSheet.getRange("A3:C3"));
sweSheet.getRange("B6:C6").format.numberFormat = "0.0%";
const gold = swebench.gold_preflight || {};
const goldRequired = gold.required ?? 6;
const goldLocked = gold.locked_instances?.length ?? swebench.gold_valid_instances?.length ?? null;
const sweBlocker = swebench.error || (
  swebench.status === "blocked"
    ? `${gold.instances?.length ?? 0} 个固定候选已尝试；gold-valid ${goldLocked ?? 0}/${goldRequired}。详见原始 gold 日志。`
    : ""
);
sweSheet.getRange("E3:F7").values = [
  ["运行状态", "值"],
  ["状态", swebench.status || "N/A"],
  ["阶段", swebench.phase || "N/A"],
  ["Gold-valid", goldLocked == null ? "N/A" : `${goldLocked}/${goldRequired}`],
  ["阻塞说明", sweBlocker || "N/A"],
];
header(sweSheet.getRange("E3:F3"));
sweSheet.getRange("F4:F7").format = { wrapText: true };
const sweHeaders = ["Profile", "Instance ID", "Resolved", "Patch", "Trace", "官方日志", "错误"];
sweSheet.getRange("A8:G8").values = [sweHeaders];
header(sweSheet.getRange("A8:G8"));
const sweAttempts = swebench.attempts || [];
if (sweAttempts.length) {
  const rows = sweAttempts.map((item) => [item.profile, item.instance_id, item.resolved, item.patch_path, item.trace_path, item.official_log_path, item.error]);
  sweSheet.getRangeByIndexes(8, 0, rows.length, sweHeaders.length).values = rows;
  body(sweSheet.getRangeByIndexes(8, 0, rows.length, sweHeaders.length));
}
sweSheet.freezePanes.freezeRows(8);
const sweLastRow = Math.max(9, 8 + sweAttempts.length);
sweSheet.getRange(`A1:G${sweLastRow}`).format.columnWidth = 20;
sweSheet.getRange(`B1:B${sweLastRow}`).format.columnWidth = 34;
sweSheet.getRange(`D1:G${sweLastRow}`).format.columnWidth = 44;
sweSheet.getRange(`E1:E${sweLastRow}`).format.columnWidth = 20;
sweSheet.getRange(`F1:F${sweLastRow}`).format.columnWidth = 52;

// 保留探针
const retSheet = addSheet("保留探针");
title(retSheet, "A1:I1", "信息保留探针（与官方解决率分列）");
const r0 = swebench.retention?.[sweProfiles[0]] || {};
const r1 = swebench.retention?.[sweProfiles[1]] || {};
retSheet.getRange("A3:D5").values = [
  ["Profile", "通过探针", "探针总数", "保留率"],
  [sweProfiles[0] || "baseline", r0.passed ?? null, r0.total ?? null, null],
  [sweProfiles[1] || "candidate", r1.passed ?? null, r1.total ?? null, null],
];
retSheet.getRange("D4:D5").formulas = [["=IF(C4=0,\"\",B4/C4)"], ["=IF(C5=0,\"\",B5/C5)"]];
retSheet.getRange("D4:D5").format.numberFormat = "0.0%";
header(retSheet.getRange("A3:D3"));
const retHeaders = ["Profile", "Instance ID", "Probe ID", "类别", "通过", "预期SHA256", "证据SHA256", "证据角色", "证据路径"];
retSheet.getRange("A7:I7").values = [retHeaders];
header(retSheet.getRange("A7:I7"));
const probes = swebench.retention_probes || [];
if (probes.length) {
  const rows = probes.map((item) => [item.profile, item.instance_id, item.probe_id, item.category, item.passed, item.expected_sha256, item.evidence_sha256, item.evidence_role, item.evidence_path]);
  retSheet.getRangeByIndexes(7, 0, rows.length, retHeaders.length).values = rows;
  body(retSheet.getRangeByIndexes(7, 0, rows.length, retHeaders.length));
}
retSheet.freezePanes.freezeRows(7);
const retentionLastRow = Math.max(8, 7 + probes.length);
retSheet.getRange(`A1:I${retentionLastRow}`).format.columnWidth = 18;
retSheet.getRange(`B1:D${retentionLastRow}`).format.columnWidth = 32;
retSheet.getRange(`F1:G${retentionLastRow}`).format.columnWidth = 34;
retSheet.getRange(`I1:I${retentionLastRow}`).format.columnWidth = 48;

// 证据索引
const evidence = addSheet("证据索引");
title(evidence, "A1:D1", "原始证据索引与来源");
evidence.getRange("A3:D3").values = [["类别", "证据/来源", "状态", "说明"]];
header(evidence.getRange("A3:D3"));
const evidenceRows = [
  ["Manifest", report.manifest?.source || "", report.manifest?.fingerprint ? "locked" : "missing", "不可变实验清单"],
  ["Evidence root", report.evidence_root || "", report.status || "", "运行证据根目录"],
  ["SWE-bench-Live", report.manifest?.revisions?.swebench_repository || "", report.manifest?.revisions?.swebench_revision || "", "官方仓库"],
  ["Dataset", "https://huggingface.co/datasets/SWE-bench-Live/SWE-bench-Live", report.manifest?.revisions?.dataset_revision || "", "官方数据集"],
  ["Baseline", report.manifest?.revisions?.baseline_commit || "", "git object", "上下文修复前"],
  ["Candidate", report.manifest?.revisions?.candidate_commit || "", "git object", "上下文修复后"],
];
evidence.getRangeByIndexes(3, 0, evidenceRows.length, 4).values = evidenceRows;
body(evidence.getRangeByIndexes(3, 0, evidenceRows.length, 4));
evidence.getRange("A1:D9").format.columnWidth = 24;
evidence.getRange("B1:B9").format.columnWidth = 64;
evidence.getRange("D1:D9").format.columnWidth = 32;

for (const sheet of [summary, mcpSheet, permSheet, sweSheet, retSheet, evidence]) {
  const used = sheet.getUsedRange();
  used.format.autofitRows();
}

const overviewCheck = await workbook.inspect({
  kind: "table",
  range: "总览!A1:H20",
  include: "values,formulas",
  tableMaxRows: 20,
  tableMaxCols: 8,
  maxChars: 6000,
});
console.log(overviewCheck.ndjson);
const formulaErrors = await workbook.inspect({
  kind: "match",
  searchTerm: "#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A",
  options: { useRegex: true, maxResults: 300 },
  summary: "chTA final formula error scan",
  maxChars: 6000,
});
console.log(formulaErrors.ndjson);

const previewDir = path.join(path.dirname(outputPath), "workbook-previews");
await fs.mkdir(previewDir, { recursive: true });
for (const sheetName of ["总览", "MCP明细", "权限事件", "SWEbench实例", "保留探针", "证据索引"]) {
  const preview = await workbook.render({
    sheetName,
    autoCrop: "all",
    scale: 1,
    format: "png",
  });
  await fs.writeFile(
    path.join(previewDir, `${sheetName}.png`),
    new Uint8Array(await preview.arrayBuffer()),
  );
}

await fs.mkdir(path.dirname(outputPath), { recursive: true });
const output = await SpreadsheetFile.exportXlsx(workbook);
await output.save(outputPath);
