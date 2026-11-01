const f = await eda.sch_ManufactureData.getNetlistFile('check.net', 'EasyEDA');
const j = JSON.parse(await f.text());
const out = {};
for (const c of Object.values(j.components)) {
    out[c.props.Designator] = Object.fromEntries(Object.entries(c.pinInfoMap).map(([k, v]) => [k, v.net]));
}
return out;
