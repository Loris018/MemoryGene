#!/usr/bin/env node
/*
 * extract_asar.js - read files out of the DeepSeek Harness Electron `app.asar`
 * without the `asar` npm package, for evidence-grade source reading.
 *
 * Why this script exists
 * ----------------------
 * The asar format pads the JSON header to a 4-byte boundary before file data.
 * A naive extractor that starts file data at `16 + headerSize` (the shape of
 * many snippets on the web) shifts every extracted file by -(pad) bytes: the
 * first bytes of the previous file leak in and the last bytes of the wanted
 * file are cut off. For a JS file that is enough to corrupt line numbers by
 * one and to drop the trailing newline, which matters when a report cites
 * `package/lib/index.js:150`.
 *
 * Correct data base for app.asar 0.2.1-rc.2:
 *   pad       = (4 - (headerSize % 4)) % 4      // 2 for this archive
 *   dataBase  = 16 + headerSize + pad           // 4780404
 *
 * Usage
 * -----
 *   node tools/dsh/extract_asar.js                       # list top-level dirs
 *   node tools/dsh/extract_asar.js --prefix /dsh/node_modules/@deepseek-ai/dsh-skill-filesystem
 *   node tools/dsh/extract_asar.js /dsh/node_modules/@deepseek-ai/dsh-tool-skill/lib/index.js
 *   node tools/dsh/extract_asar.js --out /tmp/dsh-src --prefix /dsh/node_modules/@deepseek-ai/dsh-tool-skill
 *
 * Defaults: --asar /Applications/DeepSeek Harness.app/Contents/Resources/app.asar
 *           --out  /tmp/dsh-asar-extract
 * Extracted paths mirror the archive paths (e.g. /tmp/dsh-asar-extract/dsh/node_modules/...).
 * Read-only on the archive; writes only under --out.
 */
'use strict';

const fs = require('node:fs');
const path = require('node:path');

const DEFAULT_ASAR = '/Applications/DeepSeek Harness.app/Contents/Resources/app.asar';
const DEFAULT_OUT = '/tmp/dsh-asar-extract';

function parseArgs(argv) {
  const args = { asar: DEFAULT_ASAR, out: DEFAULT_OUT, prefix: undefined, entries: [] };
  for (let i = 2; i < argv.length; i += 1) {
    const arg = argv[i];
    if (arg === '--asar') args.asar = argv[++i];
    else if (arg === '--out') args.out = argv[++i];
    else if (arg === '--prefix') args.prefix = argv[++i];
    else if (arg === '--help' || arg === '-h') args.help = true;
    else args.entries.push(arg);
  }
  return args;
}

function openArchive(file) {
  const fd = fs.openSync(file, 'r');
  const sizeField = Buffer.alloc(16);
  fs.readSync(fd, sizeField, 0, 16, 0);
  const headerSize = sizeField.readUInt32LE(12);
  const headerBuffer = Buffer.alloc(headerSize);
  fs.readSync(fd, headerBuffer, 0, headerSize, 16);
  const header = JSON.parse(headerBuffer.toString('utf8').replace(/\0+$/, ''));
  const pad = (4 - (headerSize % 4)) % 4;
  return { fd, header, headerSize, pad, dataBase: 16 + headerSize + pad };
}

function findNode(header, archivePath) {
  const parts = archivePath.split('/').filter(Boolean);
  let node = header;
  for (const part of parts) {
    if (!node.files || !node.files[part]) return null;
    node = node.files[part];
  }
  return node;
}

function isDirectoryNode(node) {
  return node !== null && node !== undefined && typeof node.files === 'object' && node.files !== null;
}

function walkFiles(node, archivePath, visit) {
  for (const [name, child] of Object.entries(node.files || {})) {
    const childPath = `${archivePath}/${name}`;
    if (isDirectoryNode(child)) walkFiles(child, childPath, visit);
    else visit(childPath, child);
  }
}

function extract(archive, archivePath, outDir) {
  const node = findNode(archive.header, archivePath);
  if (node === null) {
    console.error(`MISS ${archivePath}`);
    return 0;
  }
  if (isDirectoryNode(node)) {
    let count = 0;
    walkFiles(node, archivePath, (childPath, childNode) => {
      count += extract(archive, childPath, outDir) ? 1 : 0;
    });
    return count;
  }
  const buffer = Buffer.alloc(node.size);
  fs.readSync(archive.fd, buffer, 0, node.size, archive.dataBase + Number(node.offset));
  const outPath = path.join(outDir, archivePath);
  fs.mkdirSync(path.dirname(outPath), { recursive: true });
  fs.writeFileSync(outPath, buffer);
  return 1;
}

function main() {
  const args = parseArgs(process.argv);
  if (args.help) {
    console.log(fs.readFileSync(__filename, 'utf8').split('* Usage')[1].split('*/')[0]);
    return;
  }
  const archive = openArchive(args.asar);
  fs.mkdirSync(args.out, { recursive: true });
  if (args.entries.length === 0 && !args.prefix) {
    console.log(`asar: ${args.asar}`);
    console.log(`headerSize=${archive.headerSize} pad=${archive.pad} dataBase=${archive.dataBase}`);
    console.log('top-level:', Object.keys(archive.header.files));
    return;
  }
  const targets = args.prefix ? [args.prefix] : args.entries;
  let total = 0;
  for (const target of targets) total += extract(archive, target, args.out);
  console.log(
    `extracted ${total} file(s) to ${args.out} (headerSize=${archive.headerSize} pad=${archive.pad} dataBase=${archive.dataBase})`,
  );
}

main();
