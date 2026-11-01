// Export the drawing as SVG, for review without opening the client.
// getSvgFile(name) is the only drawing export in this build (there is also
// getPngFile; the SVG is better because it stays readable and diffs as text).
// The file is returned whole, so the CLI output is large -- redirect it.
const f = await eda.sch_ManufactureData.getSvgFile('main_board.svg');
if (!f) return { error: 'getSvgFile returned null' };
const text = await f.text();
return { svg: text };
