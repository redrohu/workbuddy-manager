import type {Metadata} from 'next';
import localFont from 'next/font/local';
import {Toaster} from '@/components/ui/sonner';
import {ThemeProvider} from '@/components/common/layout/ThemeProvider';
import {AuthProvider} from '@/lib/auth-context';
import {I18nProvider} from '@/lib/i18n/provider';
import {withBasePath} from '@/lib/base-path';
import {fontScaleBootScript} from '@/lib/display-prefs';
import './globals.css';

// 字体改为随仓库分发的本地文件：原来用 next/font/google 时，构建期必须联网访问
// fonts.googleapis.com 拉 CSS 与 woff2。GitHub Actions、国内 Docker 构建经常连不上
// （next/font 只会报一句含糊的 `TypeError: Cannot read properties of null`），整个
// next build 直接失败，镜像也就建不出来。字体文件与原先 google 版本同源、同子集
// （latin），appearance 不变，但构建不再依赖外网。
const inter = localFont({
  src: './fonts/Inter-variable.woff2',
  variable: '--font-inter',
  display: 'swap',
  weight: '100 900',
});

const notoSansSC = localFont({
  src: './fonts/NotoSansSC-variable.woff2',
  variable: '--font-noto-sans-sc',
  display: 'swap',
  weight: '300 700',
});

export const metadata: Metadata = {
  title: {
    template: '%s - WorkBuddy Manager',
    default: 'WorkBuddy Manager',
  },
  /**
   * 站点描述用英文：它是构建期写进静态 HTML 的元数据，无法跟随运行时语言切换
   * （管理端本身不做语言路由，见 lib/i18n/config.ts 的说明）。选英文是因为
   * 分享卡片 / 搜索引擎抓取时它面向的受众最广；界面内的文案全部走 i18n。
   */
  description: 'WorkBuddy Manager - Tencent CodeBuddy account pool console and OpenAI-compatible gateway',
  // 图标 / 清单的 URL 也要带部署前缀（PR #60 评审补漏）：Next 只给 `_next`
  // 静态资源与 next/link 跳转补 basePath，**不会**改写 metadata 里的这些字符串
  // ——实测子路径部署下产物里仍是 `href="/favicon/..."`，会被请求到域名根（通常是
  // 另一个站点）而 404，表现为「站点图标不见了、PWA 清单取不到」。根路径部署时
  // withBasePath 原样返回，行为不变。
  manifest: withBasePath('/favicon/site.webmanifest'),
  icons: {
    icon: [
      {url: withBasePath('/favicon/favicon-32x32.png'), sizes: '32x32', type: 'image/png'},
      {url: withBasePath('/favicon/favicon-16x16.png'), sizes: '16x16', type: 'image/png'},
    ],
    shortcut: withBasePath('/favicon/favicon.ico'),
    apple: withBasePath('/favicon/apple-touch-icon.png'),
  },
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html
      lang="zh-CN"
      className={`${inter.variable} ${notoSansSC.variable} hide-scrollbar font-sans`}
      suppressHydrationWarning
    >
      <body
        className={`${inter.variable} ${notoSansSC.variable} hide-scrollbar font-sans antialiased`}
      >
        {/*
          字号档位的「首帧」脚本：必须在 React 挂载前把用户选的倍数写到 <html> 上，
          否则会先画一帧默认字号再跳成自己选的那档（看上去像闪一下）。
          脚本内容由 lib/display-prefs.ts 的常量拼出来（不在这里另写一份 key 与
          倍数表），并有 Node 行为测试真的执行它。
          `suppressHydrationWarning` 挂在 <html> 上（已存在）：脚本改的是行内
          style，服务端没有这一项，不抑制会报水合不一致。
        */}
        <script dangerouslySetInnerHTML={{__html: fontScaleBootScript()}} />
        <ThemeProvider
          attribute="class"
          defaultTheme="system"
          enableSystem
          disableTransitionOnChange
        >
          <I18nProvider>
            <AuthProvider>
              {children}
              <Toaster />
            </AuthProvider>
          </I18nProvider>
        </ThemeProvider>
      </body>
    </html>
  );
}
