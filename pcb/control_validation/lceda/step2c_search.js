const queries = ['HoJLR2512-2W-1mR', 'RTT2512R001FTG', 'FRL2512FR001TS', 'GRM32ER61E107KA12',
                 'TMK325ABJ107MM', 'CL32A107MVLNNE', 'MX126-5.0-04P', 'SS34_C8678'];
const out = {};
for (const q of queries) {
    try {
        const items = await eda.lib_Device.search(q);
        out[q] = items.slice(0, 3).map((d) => ({ name: d.name, uuid: d.uuid,
            lcsc: d.supplierId, footprint: d.footprintName || d.footprint || null }));
    } catch (e) { out[q] = String(e); }
}
return out;
