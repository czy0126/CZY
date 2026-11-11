# 审阅结论（基于所附代码，不跑 EDA、不做实测）

## 一、你指出的两个缺陷——确认成立，且是同一类“假通过”

### 缺陷 1：`compare_actual_drc` 只遍历 `before`
```python
if any(after.get(k,0)>v for k,v in before.items()):
```
- 只检查 `before` 里已有的类别，`after` 中**新出现**的类别（比如 “Routing Error”、“Silkscreen Error”、“Drill Error”）不会被比较，直接漏过。
- 只要新类别不在 `before` 里，`after.get(k,0)` 根本不会被访问。
- 而且 `after.get("Physical Error",0)>0` 之前就对 Physical 做了硬门，其它未知类别完全裸奔。

### 缺陷 2：`categories` 没验证结构
```python
def categories(data: dict) -> dict:
    gr=data["value"]["raw"]
    if not isinstance(gr,list):raise ValueError("DRC category list missing")
    names=[x["name"] for x in gr]
    if len(set(names))!=len(names):raise ValueError("Duplicate native DRC categories")
    return {x["name"]:sum(len(t.get("list") or []) for t in x.get("list") or []) for x in gr}
```
- 只校验了 `raw` 是 list、名字不重复。
- 未校验：`data["ok"] is True`；`"value" in data` 且是 dict；`"raw" in data["value"]`；每个 `x` 是 dict 且有 `"name"` 是 str；`x["list"]` 是 list；每个 `t` 是 dict。
- `x.get("list") or []` 会把 `None`、`0`、`""`、`False`、空 dict 都当空列表——**空 raw 或半坏 raw 会静默返回 `{}`**，然后 `compare_actual_drc` 里 `after.get("Connection Error",0)=0 < 199` 判定“降低成功”，直接假通过。
- 同理，如果 `AFTER_DRC` 整个是 `{"ok": true}` 没 `value`，`data["value"]` 会 KeyError，但那是崩溃不是假通过；真正危险的是“结构合法但列表为空/被截断”。

### 缺陷 3（你没点但同在 `apply` 里）：`compare_actual_drc` 假定 `before` 一定有 `Connection Error` 键
`before["Connection Error"]` 若 `categories` 返回空 dict 会 KeyError——**崩溃而非假通过**，但反过来说明 `categories` 没有“必须包含 Connection/Netlist”的完整性断言。基线 199/1 的断言依赖 `categories` 返回的键存在，而 `categories` 本身没保证。

## 二、最小修复（不打乱任何路由/几何）

### 修 `categories`：加结构断言 + 空 raw 显式失败
```python
REQUIRED_FIELDS = ("name",)

def categories(data: dict) -> dict:
    if not isinstance(data, dict):
        raise ValueError("DRC payload not a dict")
    if data.get("ok") is not True:
        raise ValueError("DRC payload ok is not True")
    v = data.get("value")
    if not isinstance(v, dict):
        raise ValueError("DRC payload value missing/not dict")
    gr = v.get("raw")
    if not isinstance(gr, list):
        raise ValueError("DRC category list missing (raw not list)")
    if not gr:
        raise ValueError("DRC raw is empty; refusing to treat as zero errors")
    out = {}
    for x in gr:
        if not isinstance(x, dict):
            raise ValueError("DRC category entry not dict")
        name = x.get("name")
        if not isinstance(name, str) or not name:
            raise ValueError("DRC category entry missing/empty name")
        lst = x.get("list")
        if lst is None:
            lst = []
        if not isinstance(lst, list):
            raise ValueError(f"DRC category {name} list not list")
        n = 0
        for t in lst:
            if not isinstance(t, dict):
                raise ValueError(f"DRC category {name} item not dict")
            sub = t.get("list")
            if sub is None:
                sub = []
            if not isinstance(sub, list):
                raise ValueError(f"DRC category {name} sub-list not list")
            n += len(sub)
        if name in out:
            raise ValueError(f"Duplicate native DRC category {name}")
        out[name] = n
    for must in ("Connection Error", "Netlist Error"):
        if must not in out:
            raise ValueError(f"DRC missing mandatory category {must}")
    return out
```
要点：
- `ok is True`、`value` 是 dict、`raw` 非空、每层是 dict/list 显式校验。
- 不再用 `x.get("list") or []` 的 falsy 折叠，改为显式 `None→[]`，其它类型直接 raise。
- **强制 Connection Error / Netlist Error 必须存在**——堵住“raw 空 / 类别缺失 → 0 错误”的假通过。

### 修 `compare_actual_drc`：双向比较 + 硬卡关键类别
```python
def compare_actual_drc() -> dict:
    before = P.categories(json.loads(P.DRC.read_text(encoding="utf-8")))
    after  = P.categories(json.loads(AFTER_DRC.read_text(encoding="utf-8")))

    if before["Connection Error"] != 199 or before["Netlist Error"] != 1:
        raise ValueError("Original native 199/1 DRC baseline changed")
    if after.get("Connection Error", 0) >= before["Connection Error"]:
        raise ValueError("Native routing did NOT reduce the 199 open connections")
    if after.get("Netlist Error", 0) > 1:
        raise ValueError("Native routing grew netlist errors")
    if after.get("Physical Error", 0) > 0:
        raise ValueError("Native routing introduced physical error")

    # 双向：after 不允许任何类别相对 before 增长（含 before 没有的类别）
    for k, v in after.items():
        if v > before.get(k, 0):
            raise ValueError(f"DRC category {k} grew {before.get(k,0)}->{v}")
    # before 有的类别，after 不得消失（下降必须是真的下降，不是类别被吞）
    for k in before:
        if k not in after:
            raise ValueError(f"DRC category {k} disappeared in after; suspect truncation")
    ...返回体不变...
```
关键点：
- **`after` 的任意类别 > `before` 同类别（含 before 缺省为 0）都拒绝**——这就是“新未知类别可能漏报”的堵口。
- **`before` 有而 `after` 没有的类别直接拒绝**——防止“类别被吞 → 错误消失”的另一种假通过。
- Connection Error 必须严格下降、Netlist ≤1、Physical=0 保留。

这两处改动都在 `route_open_connections.py::categories` 和 `apply_g1_open_batch.py::compare_actual_drc` 里，**不动 PAIRS、不动几何路径、不动 `issues()`/`verify()` 的铜覆盖逻辑**，不扩大批处理范围。

## 三、负例（必须是会**失败**的用例，防假通过）

按修复后的行为，以下每个都应 raise，写进测试：

1. **空 raw**：`{"ok": true, "value": {"raw": []}}` → `ValueError("DRC raw is empty...")`。旧代码返回 `{}`。
2. **缺 value**：`{"ok": true}` → `ValueError("value missing")`。
3. **ok=false**：`{"ok": false, "value": {"raw":[...]}}` → `ValueError("ok is not True")`。
4. **新类别增长**：before 无 “Drill Error”，after 出现 `{"name":"Drill Error","list":[{"list":[1,2,3]}]}` → `ValueError("Drill Error grew 0->3")`。旧代码完全放过。
5. **类别消失（截断）**：before 有 “Connection Error:199”，after 里没有这个 name → `ValueError("Connection Error disappeared...")`。旧代码 `after.get(...)=0` 反而判定“降低成功”。
6. **list 是 0 / 字符串**：`{"name":"Connection Error","list":0}` 或 `"list":"wrong"` → `ValueError("list not list")`。旧代码 `or []` 折叠成 0。
7. **item 非 dict**：`{"name":"X","list":[42]}` → `ValueError("item not dict")`。
8. **name 缺失/空**：`{"list":[]}` 或 `{"name":"","list":[]}` → `ValueError`。
9. **缺失强制类别**：after 里没有 “Netlist Error” → `ValueError("missing mandatory category Netlist Error")`。
10. **物理错误新增**：after Physical Error=1 → `ValueError("introduced physical error")`（保留原逻辑，但要覆盖测试）。
11. **Connection 不降反升**：after=200 → `ValueError("did NOT reduce")`。
12. **Netlist 超 1**：after Netlist=2 → `ValueError("grew netlist errors")`。
13. 回归：**正常一次下降**（199→183、Netlist=1、Physical=0、无新类别），`ok=True`、`native_connection_errors_reduced=16`、