const queries = ['100uF 25V SMD', 'RVT1E101M1010', 'UWT1E101MCL', '100uF 35V 1210',
                 'VT1E101M1010', '50V100UF 8*10'];
const out = {};
for (const q of queries) {
    try {
        const items = await eda.lib_Device.search(q);
        out[q] = items.slice(0, 5).map((d) => ({ name: d.name, uuid: d.uuid,
            lcsc: d.supplierId, footprint: d.footprintName || d.footprint || null }));
    } catch (e) { out[q] = String(e); }
}
return out;
