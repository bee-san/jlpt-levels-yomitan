#!/usr/bin/env node

import {readFile} from 'node:fs/promises';
import {resolve} from 'node:path';
import {pathToFileURL} from 'node:url';

function fail(message) {
    throw new Error(message);
}

if (process.argv.length !== 5) {
    fail('usage: yomitan_import_probe.mjs YOMITAN_CHECKOUT DICTIONARY_ZIP EXPECTED_JSON');
}

const yomitanRoot = resolve(process.argv[2]);
const dictionaryPath = resolve(process.argv[3]);
const expectedPath = resolve(process.argv[4]);
const importFrom = async (relativePath) => import(pathToFileURL(resolve(yomitanRoot, relativePath)));

const {IDBFactory, IDBKeyRange} = await import(resolve(yomitanRoot, 'node_modules/fake-indexeddb/build/esm/index.js'));
const {DictionaryDatabase} = await importFrom('ext/js/dictionary/dictionary-database.js');
const {DictionaryImporter} = await importFrom('ext/js/dictionary/dictionary-importer.js');
const {DictionaryImporterMediaLoader} = await importFrom('test/mocks/dictionary-importer-media-loader.js');

globalThis.self = {constructor: {name: 'Window'}};
globalThis.Worker = function Worker() {
    return {addEventListener() {}, terminate() {}};
};
globalThis.IDBKeyRange = IDBKeyRange;
globalThis.indexedDB = new IDBFactory();

const expected = JSON.parse(await readFile(expectedPath, 'utf8'));
if (!Array.isArray(expected.probes) || expected.probes.length === 0) {
    fail('expected JSON must contain a non-empty probes array');
}

const archiveBytes = await readFile(dictionaryPath);
const archiveData = archiveBytes.buffer.slice(archiveBytes.byteOffset, archiveBytes.byteOffset + archiveBytes.byteLength);
const database = new DictionaryDatabase();
await database.prepare();
try {
    const importer = new DictionaryImporter(new DictionaryImporterMediaLoader());
    const {result, errors} = await importer.importDictionary(
        database,
        archiveData,
        {prefixWildcardsSupported: false, yomitanVersion: '0.0.0.0'},
    );
    if (errors.length !== 0) {
        fail(`Yomitan importer returned ${errors.length} error(s): ${errors.map((error) => error.message).join('; ')}`);
    }
    if (result === null || result.title !== expected.title) {
        fail(`imported title mismatch: ${result?.title ?? '<null>'}`);
    }
    const titles = new Map([[expected.title, {alias: expected.title, allowSecondarySearches: false}]]);
    const terms = expected.probes.map(({term}) => term);
    const metas = await database.findTermMetaBulk(terms, titles);
    const normalized = metas.map((item) => ({
        dictionary: item.dictionary,
        mode: item.mode,
        reading: item.data?.reading,
        term: item.term,
        value: item.data?.frequency?.value,
        displayValue: item.data?.frequency?.displayValue,
    }));
    for (const probe of expected.probes) {
        const matching = normalized.filter((item) =>
            item.dictionary === expected.title &&
            item.term === probe.term &&
            item.reading === probe.reading &&
            item.mode === 'freq' &&
            item.value === probe.value &&
            item.displayValue === probe.displayValue
        );
        if (matching.length !== 1) {
            fail(`lookup mismatch for ${probe.term}/${probe.reading}: ${JSON.stringify(matching)}`);
        }
    }
    process.stdout.write(`${JSON.stringify({importErrors: 0, importedTitle: result.title, probes: normalized})}\n`);
} finally {
    await database.close();
}
