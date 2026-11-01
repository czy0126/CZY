const f = await eda.sch_ManufactureData.getNetlistFile('probe.net', 'EasyEDA');
const j = JSON.parse(await f.text());
const out = {};
for (const [k, c] of Object.entries(j.components)) {
    out[k] = { ref: c.props.Designator, keys: Object.keys(c), pins: c.pins || c.pin || null };
}
return out;
