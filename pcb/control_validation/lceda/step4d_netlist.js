const nl = await eda.sch_Netlist.getNetlist();
return String(nl).slice(0, 2000);
