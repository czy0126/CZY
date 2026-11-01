const sysLib = await eda.lib_LibrariesList.getSystemLibraryUuid();
const queries = ['UCC24624DR', 'BSC010N04LS6', '2N7002', 'SMBJ15A', 'SS34', '0603WAF1001T5E',
                 '0603WAF1002T5E', '0603WAF1003T5E', '0603WAF0000T5E', '0805W8F0000T5E',
                 '0.001R 2512', '10uF 35V 1210', '1uF 35V 0805', '100nF 50V 0603',
                 '2.2uF 25V 1206', '10uF 25V 0805', '100uF 25V', '0.5A 1206 fuse',
                 'MX126-5.0-02P', 'test point'];
const out = {};
for (const q of queries) {
    try {
        const items = await eda.lib_Device.search(q);
        out[q] = items.slice(0, 4).map((d) => ({ name: d.name, uuid: d.uuid,
            lcsc: d.supplierId, lib: d.libraryUuid }));
    } catch (e) {
        out[q] = String(e);
    }
}
return { systemLibrary: sysLib, results: out };
