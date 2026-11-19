// ocr_jxa.js — OCR docs/img screenshots via macOS Vision framework (JXA, no compilation)
ObjC.import('Vision');
ObjC.import('AppKit');
ObjC.import('Foundation');

function ocrImage(filePath) {
  const img = $.NSImage.alloc.initWithContentsOfFile(filePath);
  if (img.isNil()) return '[image load failed]';
  const cg = img.CGImageForProposedRectContextHints(null, null, null);
  if (cg.isNil()) return '[cgImage failed]';
  const handler = $.VNImageRequestHandler.alloc.initWithCGImageOptions(cg, $.NSDictionary.dictionary);
  const req = $.VNRecognizeTextRequest.alloc.init;
  req.recognitionLevel = 0; // accurate
  req.usesLanguageCorrection = true;
  req.recognitionLanguages = $.NSArray.arrayWithArray(['zh-Hans', 'en-US']);
  const errPtr = Ref();
  const ok = handler.performRequestsError($.NSArray.arrayWithArray([req]), errPtr);
  if (!ok) return '[perform failed: ' + errPtr[0] + ']';
  const results = req.results;
  if (results.isNil()) return '';
  const lines = [];
  for (let i = 0; i < results.count; i++) {
    const obs = results.objectAtIndex(i);
    const cand = obs.topCandidates(1);
    if (cand.count === 0) continue;
    const text = cand.objectAtIndex(0).string.js;
    const box = obs.boundingBox;
    lines.push([box.origin.y + box.size.height / 2, text]); // midY; Vision origin = bottom-left
  }
  lines.sort((a, b) => b[0] - a[0]); // top-down
  return lines.map(l => l[1]).join('\n');
}

const dir = '/Users/jacky/works/science-research-project/docs/img';
const fm = $.NSFileManager.defaultManager;
const entries = fm.contentsOfDirectoryAtPathError(dir, null);
const files = [];
for (let i = 0; i < entries.count; i++) {
  const name = entries.objectAtIndex(i).js;
  if (/^IMG_14.*\.(jpe?g|png)$/.test(name)) files.push(name);
}
files.sort();

let out = '# OCR 结果（docs/img）\n\n';
for (const f of files) {
  out += '## ' + f + '\n\n```\n' + ocrImage(dir + '/' + f) + '\n```\n\n';
}
const err2 = Ref();
out.writeToFileAtomicallyEncodingError(dir + '/_ocr_output.md', true, $.NSUTF8StringEncoding, err2);
console.log('written ' + files.length + ' files -> docs/img/_ocr_output.md');
