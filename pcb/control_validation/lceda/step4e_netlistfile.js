const f = await eda.sch_ManufactureData.getNetlistFile('probe.net', 'EasyEDA');
if (!f) return { ok: false, err: 'no file' };
const text = await f.text();
return { name: f.name, size: f.size, head: text.slice(0, 1500) };
