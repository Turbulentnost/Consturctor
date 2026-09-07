import icon3ds from '../assets/fileicons/3ds-svgrepo-com.svg'
import iconAac from '../assets/fileicons/aac-svgrepo-com.svg'
import iconAi from '../assets/fileicons/ai-ai-svgrepo-com.svg'
import iconAndroid from '../assets/fileicons/android-svgrepo-com.svg'
import iconAvi from '../assets/fileicons/avi-svgrepo-com.svg'
import iconBmp from '../assets/fileicons/bmp-svgrepo-com.svg'
import iconCad from '../assets/fileicons/cad-svgrepo-com.svg'
import iconCdr from '../assets/fileicons/cdr-svgrepo-com.svg'
import iconCpp from '../assets/fileicons/cpp-svgrepo-com.svg'
import iconCss from '../assets/fileicons/css-svgrepo-com.svg'
import iconDat from '../assets/fileicons/dat-svgrepo-com.svg'
import iconDll from '../assets/fileicons/dll-svgrepo-com.svg'
import iconDmg from '../assets/fileicons/dmg-svgrepo-com.svg'
import iconDoc from '../assets/fileicons/doc-svgrepo-com.svg'
import iconDocker from '../assets/fileicons/docker-svgrepo-com.svg'
import iconEps from '../assets/fileicons/eps-svgrepo-com.svg'
import iconExcel from '../assets/fileicons/excel-svgrepo-com.svg'
import iconFla from '../assets/fileicons/fla-svgrepo-com.svg'
import iconFlv from '../assets/fileicons/flv-svgrepo-com.svg'
import iconGif from '../assets/fileicons/gif-svgrepo-com.svg'
import iconGit from '../assets/fileicons/git-svgrepo-com.svg'
import iconGithub from '../assets/fileicons/github-svgrepo-com.svg'
import iconHtml from '../assets/fileicons/html-svgrepo-com.svg'
import iconIndd from '../assets/fileicons/indd-svgrepo-com.svg'
import iconIso from '../assets/fileicons/iso-svgrepo-com.svg'
import iconJava from '../assets/fileicons/java-4-logo-svgrepo-com.svg'
import iconJs from '../assets/fileicons/js-svgrepo-com.svg'
import iconKotlin from '../assets/fileicons/kotlin-svgrepo-com.svg'
import iconMpg from '../assets/fileicons/mpg-svgrepo-com.svg'
import iconPng from '../assets/fileicons/png-svgrepo-com.svg'
import iconPython from '../assets/fileicons/python-svgrepo-com.svg'
import iconReact from '../assets/fileicons/react-svgrepo-com.svg'
import iconSvg from '../assets/fileicons/svg-svgrepo-com.svg'
import iconTxt from '../assets/fileicons/txt-svgrepo-com.svg'
import iconVue from '../assets/fileicons/vue-svgrepo-com.svg'

const ICONS: Record<string, string> = {
  '3ds': icon3ds,
  max: icon3ds,
  obj: icon3ds,
  fbx: icon3ds,
  blend: icon3ds,
  aac: iconAac,
  mp3: iconAac,
  wav: iconAac,
  ogg: iconAac,
  flac: iconAac,
  m4a: iconAac,
  wma: iconAac,
  ai: iconAi,
  apk: iconAndroid,
  aab: iconAndroid,
  avi: iconAvi,
  mkv: iconAvi,
  mov: iconAvi,
  wmv: iconAvi,
  webm: iconAvi,
  mp4: iconAvi,
  bmp: iconBmp,
  cad: iconCad,
  dwg: iconCad,
  dxf: iconCad,
  cdr: iconCdr,
  c: iconCpp,
  cc: iconCpp,
  cpp: iconCpp,
  cxx: iconCpp,
  h: iconCpp,
  hh: iconCpp,
  hpp: iconCpp,
  hxx: iconCpp,
  css: iconCss,
  scss: iconCss,
  sass: iconCss,
  less: iconCss,
  dat: iconDat,
  bin: iconDat,
  db: iconDat,
  sqlite: iconDat,
  dll: iconDll,
  so: iconDll,
  dylib: iconDll,
  dmg: iconDmg,
  pkg: iconDmg,
  doc: iconDoc,
  docx: iconDoc,
  odt: iconDoc,
  rtf: iconDoc,
  pdf: iconDoc,
  ppt: iconDoc,
  pptx: iconDoc,
  odp: iconDoc,
  dockerfile: iconDocker,
  dockerignore: iconDocker,
  eps: iconEps,
  ps: iconEps,
  xls: iconExcel,
  xlsx: iconExcel,
  xlsm: iconExcel,
  xlsb: iconExcel,
  ods: iconExcel,
  csv: iconExcel,
  fla: iconFla,
  swf: iconFla,
  flv: iconFlv,
  gif: iconGif,
  git: iconGit,
  gitignore: iconGit,
  gitattributes: iconGit,
  github: iconGithub,
  html: iconHtml,
  htm: iconHtml,
  xhtml: iconHtml,
  indd: iconIndd,
  iso: iconIso,
  zip: iconIso,
  rar: iconIso,
  '7z': iconIso,
  tar: iconIso,
  gz: iconIso,
  tgz: iconIso,
  java: iconJava,
  jar: iconJava,
  class: iconJava,
  js: iconJs,
  mjs: iconJs,
  cjs: iconJs,
  ts: iconJs,
  json: iconJs,
  xml: iconJs,
  yaml: iconJs,
  yml: iconJs,
  kt: iconKotlin,
  kts: iconKotlin,
  mpg: iconMpg,
  mpeg: iconMpg,
  mpe: iconMpg,
  png: iconPng,
  jpg: iconPng,
  jpeg: iconPng,
  webp: iconPng,
  ico: iconPng,
  py: iconPython,
  pyw: iconPython,
  ipynb: iconPython,
  jsx: iconReact,
  tsx: iconReact,
  svg: iconSvg,
  txt: iconTxt,
  log: iconTxt,
  md: iconTxt,
  markdown: iconTxt,
  ini: iconTxt,
  conf: iconTxt,
  cfg: iconTxt,
  vue: iconVue
}

export function fileTypeIconSrc(name: string): string {
  const ext = (name.split('.').pop() || '').trim().toLowerCase()
  if (ext && ICONS[ext]) return ICONS[ext]
  const base = (name.split(/[/\\]/).pop() || '').trim().toLowerCase()
  if (base && ICONS[base]) return ICONS[base]
  return iconTxt
}
