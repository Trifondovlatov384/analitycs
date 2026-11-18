/**
 * Ежедневная отправка броней из «Estadel. План продаж» в «Аналитику из росреестра».
 *
 * Установка (один раз): в таблице Расширения → Apps Script, вставить этот код,
 * выбрать функцию setup и нажать «Выполнить», разрешить доступ.
 * Дальше скрипт сам отправляет данные каждый день около 6 утра.
 * Уходят только комплекс, лот, сумма, даты, стадия, вид оплаты и вид брони — без ФИО, комиссий и ссылок.
 */
const SYNC_URL = 'https://analitycs.vercel.app/api/estadel/sync';
const SYNC_TOKEN = '__TOKEN__';

const SHEETS = {
  'Брони Крым': 'Крым',
  'Брони Орлы Крым': 'Орлы Крым',
  'Брони Анапа': 'Анапа',
  'Брони Сочи': 'Сочи',
  'Брони Акулы ЖК': 'Акулы ЖК',
  'Брони Эстадель Лайт': 'Эстадель Лайт',
};
const DEAL_STAGES = ['комиссия полностью получена', 'сделка состоялась', 'пв забран, ждем рассрочку', 'пв внесен', 'оформление ипотеки'];

function setup() {
  ScriptApp.getProjectTriggers().forEach((t) => {
    if (t.getHandlerFunction() === 'syncEstadel') ScriptApp.deleteTrigger(t);
  });
  ScriptApp.newTrigger('syncEstadel').timeBased().everyDays(1).atHour(6).create();
  syncEstadel();
}

function syncEstadel() {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  const tz = ss.getSpreadsheetTimeZone();
  const day = (v) => {
    if (v === '' || v === null) return null;
    if (Object.prototype.toString.call(v) === '[object Date]') return isNaN(v) ? null : Utilities.formatDate(v, tz, 'yyyy-MM-dd');
    const s = String(v).trim().slice(0, 10);
    let m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(s);
    if (m) return s;
    m = /^(\d{2})\.(\d{2})\.(\d{4})$/.exec(s);
    return m ? `${m[3]}-${m[2]}-${m[1]}` : null;
  };
  const num = (v) => {
    if (v === '' || v === null) return null;
    if (typeof v === 'number') return v;
    const n = Number(String(v).replace(/[\s ]/g, '').replace(',', '.'));
    return isFinite(n) ? n : null;
  };
  const rows = [];
  Object.keys(SHEETS).forEach((name) => {
    const sh = ss.getSheetByName(name);
    if (!sh) return;
    const grid = sh.getDataRange().getValues();
    if (!grid.length) return;
    const h = grid[0].map((x) => String(x).trim());
    const col = (p) => { const i = h.findIndex((x) => x.indexOf(p) === 0); return i < 0 ? null : i; };
    const iC = col('Комплекс'), iLot = col('Апарт'), iSum = col('Сумма'), iBd = col('Дата брони'), iSt = col('Стадия сделки');
    const iDd = col('Дата сделки динамическая'), iPay = col('Вид оплаты'), iSrc = col('Вид брони');
    if (iC === null || iSt === null || iBd === null) return;
    const txt = (r, i) => (i === null || r[i] === '' || r[i] === null ? null : String(r[i]).trim() || null);
    grid.slice(1).forEach((r) => {
      const cx = String(r[iC]).trim();
      if (!cx) return;
      const stage = String(r[iSt]).replace(/🗹/g, '').split(/\s+/).filter(Boolean).join(' ');
      const isDeal = DEAL_STAGES.indexOf(stage.toLowerCase()) >= 0;
      let dd = iDd !== null ? day(r[iDd]) : null;
      const fm = parseInt(num(r[2]), 10), fy = parseInt(num(r[3]), 10);
      if (isDeal && fm >= 1 && fm <= 12 && fy > 2000) {
        const key = fy + '-' + ('0' + fm).slice(-2);
        if (!dd || dd.slice(0, 7) !== key) dd = key + '-01';
      }
      rows.push({
        team: SHEETS[name], complex: cx, lot: txt(r, iLot), amount: iSum !== null ? num(r[iSum]) : null,
        booking_date: day(r[iBd]), deal_date: isDeal ? dd : null, stage: stage || null,
        payment: txt(r, iPay), lead_source: txt(r, iSrc),
      });
    });
  });
  const res = UrlFetchApp.fetch(SYNC_URL, {
    method: 'post', contentType: 'application/json', muteHttpExceptions: true,
    headers: { 'X-Sync-Token': SYNC_TOKEN },
    payload: JSON.stringify({ rows: rows, source: 'Google Sheets (автосинхронизация)' }),
  });
  console.log(res.getResponseCode() + ' ' + res.getContentText().slice(0, 500));
  if (res.getResponseCode() !== 200) throw new Error('Не удалось отправить данные: ' + res.getContentText().slice(0, 200));
}
