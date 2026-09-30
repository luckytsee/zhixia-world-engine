/**
 * 主动发起用到的文本工具（从宿主 App 的 Prompt 组装层抽出，开源版独立自带）。
 *
 * 三个职责：
 *   1. cleanSpeech       —— 洗掉模型回话里的控制标签（[笑] 之类），保持气泡干净
 *   2. stripStickerTags  —— 剥掉 [图:xxx] 标签（宿主用它发表情图；开源版只要剥掉）
 *   3. proactiveInstruction —— 把"由头"包成给模型的一句指令
 *
 * ⚠️ 这里的措辞是**指令框架**，不是台词——台词永远由模型看着世界状态自己长，
 * 见 README「只给状态不给台词」。
 */

export class WeTextKit {
  /** 已知标签词表（可按你的模型输出习惯增删） */
  private static readonly KNOWN_TAGS: string[] = [
    'neutral', 'happy', 'sad', 'angry', 'curious', 'tired', 'surprised', 'shy', 'excited',
    'wave', 'yawn', 'nod', 'shake', 'idle_01'
  ];

  /** `[图:标签]` 剥离：标签取第一个命中，正文返回剥后结果 */
  static stripStickerTags(raw: string): string {
    let out: string = '';
    let i: number = 0;
    while (i < raw.length) {
      const ch: string = raw.charAt(i);
      if (ch === '[' || ch === '［') {
        const close: number = WeTextKit.stickerCloseIndex(raw, i);
        if (close >= 0) {
          i = close + 1;
          continue;
        }
      }
      out += ch;
      i += 1;
    }
    return out;
  }

  private static stickerCloseIndex(text: string, openIdx: number): number {
    let j: number = openIdx + 1;
    while (j < text.length && WeTextKit.isSpace(text.charAt(j))) {
      j += 1;
    }
    if (text.substring(j, j + 1) !== '图') {
      return -1;
    }
    j += 1;
    while (j < text.length && WeTextKit.isSpace(text.charAt(j))) {
      j += 1;
    }
    const sep: string = text.charAt(j);
    if (sep !== ':' && sep !== '：') {
      return -1;
    }
    j += 1;
    let inner: number = 0;
    while (j < text.length) {
      const ch: string = text.charAt(j);
      if (ch === ']' || ch === '］') {
        return inner >= 1 ? j : -1;
      }
      if (ch === '[' || ch === '［' || ch === '\n') {
        return -1;
      }
      inner += 1;
      j += 1;
    }
    return -1;
  }

  /** 洗话：剥掉正文里的已知标签 + 末尾兜底短标签，再 trim */
  static cleanSpeech(raw: string): string {
    return WeTextKit.stripTrailingTag(WeTextKit.stripKnownTags(raw)).trim();
  }

  private static stripKnownTags(text: string): string {
    let out: string = '';
    let i: number = 0;
    while (i < text.length) {
      const ch: string = text.charAt(i);
      if (ch === '[' || ch === '［') {
        const close: number = WeTextKit.tagCloseIndex(text, i);
        if (close >= 0) {
          const inner: string = text.substring(i + 1, close).trim().toLowerCase();
          if (WeTextKit.KNOWN_TAGS.indexOf(inner) >= 0) {
            i = close + 1;
            continue;
          }
        }
      }
      out += ch;
      i += 1;
    }
    return out;
  }

  /** 开括号后 1-12 字、无嵌套、无换行 → 闭括号下标 */
  private static tagCloseIndex(text: string, openIdx: number): number {
    let inner: number = 0;
    let j: number = openIdx + 1;
    while (j < text.length && inner < 12) {
      const ch: string = text.charAt(j);
      if (ch === ']' || ch === '］') {
        return inner >= 1 ? j : -1;
      }
      if (ch === '[' || ch === '［' || ch === '\n') {
        return -1;
      }
      inner += 1;
      j += 1;
    }
    return -1;
  }

  /** 末尾一个短标签兜底剥（未知新词也拦得住） */
  private static stripTrailingTag(text: string): string {
    let end: number = text.length;
    while (end > 0 && WeTextKit.isSpace(text.charAt(end - 1))) {
      end -= 1;
    }
    if (end === 0) {
      return text;
    }
    const last: string = text.charAt(end - 1);
    if (last !== ']' && last !== '］') {
      return text;
    }
    let j: number = end - 2;
    let inner: number = 0;
    while (j >= 0) {
      const ch: string = text.charAt(j);
      if (ch === '[' || ch === '［') {
        return inner >= 1 ? text.substring(0, j) : text;
      }
      if (ch === ']' || ch === '］' || ch === '\n') {
        return text;
      }
      inner += 1;
      if (inner > 12) {
        return text;
      }
      j -= 1;
    }
    return text;
  }

  private static isSpace(ch: string): boolean {
    return ch === ' ' || ch === '\n' || ch === '\t' || ch === '\r'
      || ch === '\f' || ch === '\v';
  }

  /** 'YYYY-MM-DD'（本地时区） */
  static ymd(ms: number): string {
    const d = new Date(ms);
    return d.getFullYear().toString().padStart(4, '0') + '-'
      + (d.getMonth() + 1).toString().padStart(2, '0') + '-'
      + d.getDate().toString().padStart(2, '0');
  }

  /**
   * 把"由头"包成指令，交给模型。**这不是台词**——只告诉它"为什么现在开口"，
   * 具体说什么由它看着注入的世界状态自己决定。
   */
  static proactiveInstruction(hint: string): string {
    return '（请主动发一条消息。' + hint + '。'
      + '只输出你要发的那句话本身，一两句就好——'
      + '别解释你在完成任务、别复述"由头"两个字、别提任何指示。）';
  }
}
