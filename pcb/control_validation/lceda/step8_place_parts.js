const LIB = '0819f05c4eef4c71ace90d822a990e87';
const D = {
    U1: '1d0fb5a952ca4767adbbe375aaa2f4d6', Q1: '0f8c3cb199e34e21a1caae1a094d4461',
    Q2: '0f8c3cb199e34e21a1caae1a094d4461', Q4: '4bf6fb56f0a44a96860771f6cfb8e6d4',
    D1: '9a1593d1216344c29a56d306ce854ef8', D2: '009407eaaa604eb9b6f73cc3868f316d',
    C1: 'a4eead9810994d70a92229349f8ce5fe', C2: '89c7d63b9d074e6dae4b7baf00fed93b',
    C3: 'ac7072e4a0764739a31216c96ed3c9cc', C4: 'aed895b43eef417a979c38d409c303a9',
    C5: 'ac7072e4a0764739a31216c96ed3c9cc', C6: '56f44ff5caba468fb77a1e1ed80c1a85',
    C7: 'f0c7df795bfa440791f22a6df319d993', R1: 'cc760290addf45e2b9b29f9e4433b86a',
    R2: 'a66c7d5e07674b0085ed1af2f8ebfc3a', R3: 'a66c7d5e07674b0085ed1af2f8ebfc3a',
    R4: '7696e5ef97934e7985ae08c81ed833f2', R5: '18db11499a04403ba8c98e2f7a687fbc',
    R6: '18db11499a04403ba8c98e2f7a687fbc', Rg1: 'a66c7d5e07674b0085ed1af2f8ebfc3a',
    Rg2: 'a66c7d5e07674b0085ed1af2f8ebfc3a', Rgs1: '9b698a84139c4c4b998625f003a0615f',
    Rgs2: '9b698a84139c4c4b998625f003a0615f', Rsn1: '91ed62e3d3584de481255b4ba4b37f6f',
    Rsn2: '91ed62e3d3584de481255b4ba4b37f6f', Rsh1: '691f222f861d4e0aaaf6743ddce33e09',
    Rsh2: '691f222f861d4e0aaaf6743ddce33e09', Csn1: 'f7218f4330f6417aa864e05da749dbcb',
    Csn2: 'f7218f4330f6417aa864e05da749dbcb', CGL1: 'c74941d6817646f69deaa1b20fd8a8c1',
    CGL2: 'c74941d6817646f69deaa1b20fd8a8c1', F1: '4ae5b662af7f4c0089d136241f4ee296',
    J1: '4cdad34c35574de3b1f855c100b741d3', J2: '4cdad34c35574de3b1f855c100b741d3',
    J3: 'cb4a6c45ff314d4185c444788a37f6e2', JP1: '99b1039acd624894acb0c01cac9f07f5',
    JP2: '99b1039acd624894acb0c01cac9f07f5', TP1: 'a0e59b8855a7442383da6e1a35112e6f',
    TP2: 'a0e59b8855a7442383da6e1a35112e6f', TP3: 'a0e59b8855a7442383da6e1a35112e6f',
    TP4: 'a0e59b8855a7442383da6e1a35112e6f', TP5: 'a0e59b8855a7442383da6e1a35112e6f',
    TP6: 'a0e59b8855a7442383da6e1a35112e6f', TP7: 'a0e59b8855a7442383da6e1a35112e6f',
    TP8: 'a0e59b8855a7442383da6e1a35112e6f', TP9: 'a0e59b8855a7442383da6e1a35112e6f',
    TP10: 'a0e59b8855a7442383da6e1a35112e6f', TP11: 'a0e59b8855a7442383da6e1a35112e6f',
    TP12: 'a0e59b8855a7442383da6e1a35112e6f'
};
const POS = {
    J1: [120, 120], F1: [260, 120], D2: [400, 120], D1: [540, 120], C1: [680, 120], C2: [820, 120], C3: [960, 120],
    U1: [120, 260], C4: [300, 260], C5: [440, 260], Q4: [580, 260], R4: [720, 260],
    R1: [120, 400], R2: [260, 400], R3: [400, 400], R5: [540, 400], R6: [680, 400], JP1: [820, 400], JP2: [960, 400],
    Q1: [120, 540], Q2: [260, 540], Rg1: [400, 540], Rg2: [540, 540], Rgs1: [680, 540], Rgs2: [820, 540],
    CGL1: [960, 540], CGL2: [1100, 540],
    Rsh1: [120, 680], Rsh2: [260, 680], Rsn1: [400, 680], Csn1: [540, 680], Rsn2: [680, 680], Csn2: [820, 680],
    C6: [960, 680], C7: [1100, 680],
    J3: [120, 820], J2: [300, 820],
    TP1: [120, 950], TP2: [220, 950], TP3: [320, 950], TP4: [420, 950], TP5: [520, 950], TP6: [620, 950],
    TP7: [720, 950], TP8: [820, 950], TP9: [920, 950], TP10: [1020, 950], TP11: [1120, 950], TP12: [1220, 950]
};
const out = [];
const refs = Object.keys(POS);
for (const ref of refs) {
    const dev = { libraryType: '3', libraryUuid: LIB, uuid: D[ref] };
    const [x, y] = POS[ref];
    const c = await eda.sch_PrimitiveComponent.create(dev, x, y, undefined, 0, false, true, true);
    if (!c) { out.push({ ref, error: 'create failed' }); continue; }
    const id = c.getState_PrimitiveId();
    const pre = (await eda.sch_PrimitiveComponent.get(id)).getState_OtherProperty();
    await eda.sch_PrimitiveComponent.modify(id, { designator: ref, otherProperty: pre });
    const pins = await eda.sch_PrimitiveComponent.getAllPinsByPrimitiveId(id);
    out.push({ ref, id, x, y, pins: pins.map((p) => ({
        n: p.getState_PinNumber(), name: p.getState_PinName(), x: p.x, y: p.y })) });
}
return out;
