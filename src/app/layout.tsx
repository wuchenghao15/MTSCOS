import Footer from "@/components/Footer";
import Header from "@/components/Header";
import ScrollToTop from "@/components/ScrollToTop";
import "../styles/index.css";
import { Metadata } from "next";

import { Providers } from "./providers";

export const metadata: Metadata = {
  title: "武汉文海星辰文化传媒｜武汉本地官网搭建GEO优化",
  description: "武汉本地企业官网搭建与搜索获客服务商，提供 Next.js 企业官网开发、Tailwind CSS前端定制、同城GEO优化与整站SEO优化服务。",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html suppressHydrationWarning lang="zh-CN" className="font-sans">
      <head />

      <body className="bg-[#FCFCFC] dark:bg-black">
        <Providers>
          <div className="isolate">
            <Header />
            {children}
            <Footer />
          </div>
          <ScrollToTop />
        </Providers>
      </body>
    </html>
  );
}

