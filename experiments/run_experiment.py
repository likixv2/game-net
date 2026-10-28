import assert = require('node:assert');
import { describe, it } from 'mocha';
import {
  readSnapshotFile,
  type FileAccessResult,
  type BoundedReadResult,
  type SnapshotFileAccess,
} from '../../src/core/snapshotReader';

/**
 * A fake filesystem that counts every call it receives. Counting is the
 * point of several tests: for ignored and oversized paths, the assertion is
 * not just the returned reason but that the underlying filesystem was
 * never touched at all (not even a stat). It also records the maxBytes
 * argument each read actually received, so a wrong cap is caught.
 *
 * The optional failures flag makes a method REJECT, which is how the
 * reader's exception handling is tested: an adapter bug, not an expected
 * condition.
 */
interface FakeFailures {
  readonly rejectSize?: boolean;
  readonly rejectRead?: boolean;
}

class FakeAccess implements SnapshotFileAccess {
  stats: string[] = [];
  reads: string[] = [];
  /** The maxBytes argument each readBounded() call actually received. */
  readCaps: number[] = [];

  constructor(
    private readonly size: FileAccessResult<number>,
    private readonly bounded: BoundedReadResult,
    private readonly failures: FakeFailures = {}
  ) {}

  async fileSize(path: string): Promise<FileAccessResult<number>> {
    this.stats.push(path);
    if (this.failures.rejectSize) throw new Error('unexpected filesystem failure (stat)');
    return this.size;
  }

  async readBounded(path: string, maxBytes: number): Promise<BoundedReadResult> {
    this.reads.push(path);
    this.readCaps.push(maxBytes);
    if (this.failures.rejectRead) throw new Error('unexpected filesystem failure (read)');
    return this.bounded;
  }
}

const utf8 = (text: string): Uint8Array => new TextEncoder().encode(text);
const okNum = (value: number): FileAccessResult<number> => ({ kind: 'ok', value });
const okBytes = (bytes: Uint8Array): BoundedReadResult => ({ kind: 'ok', bytes });
const MISSING = { kind: 'missing' } as const;
const STILL_MISSING = MISSING;
const ERR = { kind: 'error', detail: 'fake failure' } as const;
const TOO_LARGE = { kind: 'too-large' } as const;

/** Small custom cap keeps tests tiny; production default is the 1 MB constant. */
const opts = (access: SnapshotFileAccess, maxBytes = 10) => ({ access, maxBytes });

describe('snapshotReader', () => {
  it('reads a valid text file and returns its content', async () => {
    const access = new FakeAccess(okNum(5), okBytes(utf8('hello')));
    const result = await readSnapshotFile('src/app.ts', opts(access));
    assert.deepStrictEqual(result, { kind: 'text', text: 'hello' });
    assert.deepStrictEqual(access.stats, ['src/app.ts']);
    assert.deepStrictEqual(access.reads, ['src/app.ts']);
  });

  it('accepts an empty file as empty text', async () => {
    const access = new FakeAccess(okNum(0), okBytes(utf8('')));
    assert.deepStrictEqual(await readSnapshotFile('empty.txt', opts(access)), {
      kind: 'text',
      text: '',
    });
  });

  it('rejects an IGNORED path before any filesystem call — not even stat', async () => {
    const access = new FakeAccess(okNum(5), okBytes(utf8('hello')));
    const result = await readSnapshotFile('node_modules/pkg/index.js', opts(access));
    assert.deepStrictEqual(result, { kind: 'unavailable', reason: 'ignored' });
    assert.deepStrictEqual(access.stats, [], 'fileSize must never be called');
    assert.deepStrictEqual(access.reads, [], 'readBounded must never be called');
  });

  it('honors extraIgnoredFolders with the same segment rules as M1', async () => {
    const access = new FakeAccess(okNum(1), okBytes(utf8('x')));
    const result = await readSnapshotFile('secrets/keys.env', {
      access,
      maxBytes: 10,
      extraIgnoredFolders: ['secrets'],
    });
    assert.deepStrictEqual(result, { kind: 'unavailable', reason: 'ignored' });
    assert.strictEqual(access.stats.length + access.reads.length, 0);
  });

  it('rejects an oversized file from metadata alone, WITHOUT reading contents', async () => {
    const access = new FakeAccess(okNum(11), okBytes(utf8('never-read-me')));
    const result = await readSnapshotFile('big.txt', opts(access));
    assert.deepStrictEqual(result, { kind: 'unavailable', reason: 'too-large' });
    assert.deepStrictEqual(access.reads, [], 'oversized content must never be read');
  });

  it('accepts a file exactly at the size cap', async () => {
    const access = new FakeAccess(okNum(10), okBytes(utf8('1234567890')));
    assert.deepStrictEqual(await readSnapshotFile('exact.txt', opts(access)), {
      kind: 'text',
      text: '1234567890',
    });
  });

  it('an adapter-side too-large passes through WITHOUT any content being exposed', async () => {
    // The correct adapter rejects before handing bytes out; the reader must
    // report 'too-large' and must not have any content to decode.
    const access = new FakeAccess(okNum(6), TOO_LARGE); // e.g. grew past the cap after stat
    const result = await readSnapshotFile('bounded-big.ts', opts(access));
    assert.deepStrictEqual(result, { kind: 'unavailable', reason: 'too-large' });
  });

  it('a FAULTY adapter returning oversized ok-bytes is rejected by the reader', async () => {
    // Contract violation: ok results must never exceed maxBytes. The reader
    // is the last line of defense — it refuses without decoding.
    const access = new FakeAccess(okNum(6), okBytes(utf8('twelve chars'))); // 12 > cap 10
    const result = await readSnapshotFile('faulty.ts', opts(access));
    assert.deepStrictEqual(result, { kind: 'unavailable', reason: 'too-large' });
  });

  it('bytes larger than metadata but still within the cap are read as text, never truncated', async () => {
    // Metadata said 5 bytes, the read delivered exactly 10 (the cap). The
    // reader judges the REAL bytes it holds, so this is valid text and
    // nothing is cut off. Distinct from the 12 > cap 10 rejection above.
    const access = new FakeAccess(okNum(5), okBytes(utf8('1234567890')));
    assert.deepStrictEqual(await readSnapshotFile('growing-but-fits.ts', opts(access)), {
      kind: 'text',
      text: '1234567890',
    });
    assert.deepStrictEqual(access.readCaps, [10]);
  });

  it('reports binary content by decoding the accepted bytes', async () => {
    const access = new FakeAccess(okNum(3), okBytes(Uint8Array.from([65, 0, 66])));
    assert.deepStrictEqual(await readSnapshotFile('img.bin', opts(access)), {
      kind: 'unavailable',
      reason: 'binary',
    });
  });

  it('reports a missing file as absent without reading', async () => {
    const access = new FakeAccess(MISSING, okBytes(utf8('untouched')));
    assert.deepStrictEqual(await readSnapshotFile('gone.ts', opts(access)), { kind: 'absent' });
    assert.deepStrictEqual(access.reads, []);
  });

  it('reports an unreadable stat (e.g. permissions) without reading', async () => {
    const access = new FakeAccess(ERR, okBytes(utf8('untouched')));
    assert.deepStrictEqual(await readSnapshotFile('locked.ts', opts(access)), {
      kind: 'unavailable',
      reason: 'unreadable',
    });
    assert.deepStrictEqual(access.reads, []);
  });

  it('a file deleted between measuring and reading is absent, not a crash', async () => {
    const access = new FakeAccess(okNum(5), STILL_MISSING);
    assert.deepStrictEqual(await readSnapshotFile('vanishing.ts', opts(access)), { kind: 'absent' });
  });

  it('a read error mid-flight is unreadable, not a crash', async () => {
    const access = new FakeAccess(okNum(5), ERR);
    assert.deepStrictEqual(await readSnapshotFile('flaky.ts', opts(access)), {
      kind: 'unavailable',
      reason: 'unreadable',
    });
  });

  it('passes the configured limit to readBounded, not the default', async () => {
    const access = new FakeAccess(okNum(5), okBytes(utf8('hello')));
    await readSnapshotFile('cap.ts', opts(access, 5));
    assert.deepStrictEqual(access.readCaps, [5], 'adapter must receive the caller cap');
  });

  it('passes the default 1 MB limit to readBounded when no cap is configured', async () => {
    const access = new FakeAccess(okNum(5), okBytes(utf8('hello')));
    await readSnapshotFile('default-cap.ts', { access });
    assert.deepStrictEqual(access.readCaps, [1024 * 1024]);
  });

  it('turns a REJECTED fileSize() promise into unreadable instead of throwing', async () => {
    const access = new FakeAccess(okNum(5), okBytes(utf8('hello')), { rejectSize: true });
    assert.deepStrictEqual(await readSnapshotFile('broken-stat.ts', opts(access)), {
      kind: 'unavailable',
      reason: 'unreadable',
    });
    assert.deepStrictEqual(access.reads, [], 'a failed stat must not be followed by a read');
  });

  it('turns a REJECTED readBounded() promise into unreadable instead of throwing', async () => {
    const access = new FakeAccess(okNum(5), okBytes(utf8('hello')), { rejectRead: true });
    assert.deepStrictEqual(await readSnapshotFile('broken-read.ts', opts(access)), {
      kind: 'unavailable',
      reason: 'unreadable',
    });
    assert.deepStrictEqual(access.reads, ['broken-read.ts']);
  });

  it('fails closed on an invalid cap (negative, NaN, infinite) without any filesystem call', async () => {
    const invalidCaps = [-1, Number.NaN, Number.POSITIVE_INFINITY, Number.NEGATIVE_INFINITY];
    for (const badCap of invalidCaps) {
      const access = new FakeAccess(okNum(5), okBytes(utf8('hello')));
      assert.deepStrictEqual(
        await readSnapshotFile('cap.ts', opts(access, badCap)),
        { kind: 'unavailable', reason: 'unreadable' },
        `cap ${badCap} must be unreadable`
      );
      assert.strictEqual(access.stats.length + access.reads.length, 0, 'no filesystem access');
    }
  });

  it('treats a zero cap as valid: only an empty file is accepted', async () => {
    const emptyAccess = new FakeAccess(okNum(0), okBytes(utf8('')));
    assert.deepStrictEqual(await readSnapshotFile('empty.txt', opts(emptyAccess, 0)), {
      kind: 'text',
      text: '',
    });

    const oneByte = new FakeAccess(okNum(1), okBytes(utf8('x')));
    assert.deepStrictEqual(await readSnapshotFile('one.txt', opts(oneByte, 0)), {
      kind: 'unavailable',
      reason: 'too-large',
    });
    assert.deepStrictEqual(oneByte.reads, []);
  });

  it('fails closed on invalid metadata (negative, NaN, infinite) without reading', async () => {
    const invalidSizes = [-1, Number.NaN, Number.POSITIVE_INFINITY, Number.NEGATIVE_INFINITY];
    for (const badSize of invalidSizes) {
      const access = new FakeAccess(okNum(badSize), okBytes(utf8('hello')));
      assert.deepStrictEqual(
        await readSnapshotFile('odd-stat.ts', opts(access)),
        { kind: 'unavailable', reason: 'unreadable' },
        `size ${badSize} must be unreadable`
      );
      assert.deepStrictEqual(access.reads, [], 'invalid metadata must not cause a read');
    }
  });

  it('defaults the per-file cap to snapshotText\'s 1 MB limit', async () => {
    // No maxBytes option → the default is DEFAULT_MAX_FILE_BYTES (queried
    // via behavior, not internals): a file > 1 MB is rejected unread.
    const access = new FakeAccess(okNum(1024 * 1024 + 1), okBytes(new Uint8Array(1024 * 1024 + 1)));
    const result = await readSnapshotFile('defaults.ts', { access });
    assert.deepStrictEqual(result, { kind: 'unavailable', reason: 'too-large' });
    assert.deepStrictEqual(access.reads, []);
  });
});
