"use client";
import { useState } from "react";
import { AuroraText } from "@/components/ui/aurora-text";
import OfferList from "./OfferList";
import PricingBox from "./PricingBox";

const Pricing = (props: {
  onButtonClick?: () => void;
}) => {
  const { onButtonClick } = props;
  const [isMonthly, setIsMonthly] = useState(true);

  return (
    <section id="pricing" className="relative z-10 py-16 md:py-20 lg:py-28">
      <div className="container">
        <div className="mx-auto mb-[100px] max-w-[665px] text-center">
          <h2 className="mb-4 text-3xl font-bold leading-tight! text-black dark:text-white sm:text-4xl md:text-[45px]">
            <AuroraText
              colors={["#ff2975", "#7928CA", "#0070F3", "#38bdf8"]}
              speed={1.2}
            >
              简单实惠的定价方案
            </AuroraText>
          </h2>
          <p className="text-base leading-relaxed! text-body-color md:text-lg">
            我们提供多种定价方案，满足不同规模企业的需求。选择最适合您的方案，开始您的创业之旅。
          </p>
        </div>

        <div className="w-full">
          <div className="mb-8 flex justify-center md:mb-12 lg:mb-16">
            <span
              onClick={() => setIsMonthly(true)}
              className={`${
                isMonthly
                  ? "pointer-events-none text-primary"
                  : "text-dark dark:text-white"
              } mr-4 cursor-pointer text-base font-semibold`}
            >
              <AuroraText
                colors={["#ff2975", "#7928CA", "#0070F3", "#38bdf8"]}
                speed={1.2}
              >
                按月
              </AuroraText>
            </span>
            <div
              onClick={() => setIsMonthly(!isMonthly)}
              className="flex cursor-pointer items-center"
            >
              <div className="relative">
                <div className="h-5 w-14 rounded-full bg-[#1D2144] shadow-inner"></div>
                <div
                  className={`${
                    isMonthly ? "" : "translate-x-full"
                  } shadow-switch-1 absolute left-0 top-[-4px] flex h-7 w-7 items-center justify-center rounded-full bg-primary transition`}
                >
                  <span className="active h-4 w-4 rounded-full bg-white"></span>
                </div>
              </div>
            </div>
            <span
              onClick={() => setIsMonthly(false)}
              className={`${
                isMonthly
                  ? "text-dark dark:text-white"
                  : "pointer-events-none text-primary"
              } ml-4 cursor-pointer text-base font-semibold`}
            >
              <AuroraText
                colors={["#ff2975", "#7928CA", "#0070F3", "#38bdf8"]}
                speed={1.2}
              >
                按年
              </AuroraText>
            </span>
          </div>
        </div>

        <div className="grid grid-cols-1 gap-x-8 gap-y-10 md:grid-cols-2 lg:grid-cols-3">
          <PricingBox
            packageName="企业官网搭建 · 基础版"
            price={isMonthly ? "99" : "999"}
            duration={isMonthly ? "月" : "年"}
            subtitle={'适合个人开发者和小项目使用，快速搭建企业官网/站点，解决"没有线上门面、客户搜不到"的核心痛点'}
            onButtonClick={onButtonClick}
          >
            <OfferList text="✅ 响应式官网（适配手机/电脑）" status="active" />
            <OfferList text="✅ 单站商用授权" status="active" />
            <OfferList text="✅ 基础SEO/GEO配置" status="active" />
            <OfferList text="✅ 1次免费维护更新" status="active" />
            <OfferList text="✅ 7×12小时微信支持" status="active" />
            <OfferList text="✅ 1年访问权限" status="active" />
          </PricingBox>
          <PricingBox
            packageName="成式引擎优化 · 标准版"
            price={isMonthly ? "1999" : "19999"}
            duration={isMonthly ? "月" : "年"}
            subtitle={'适合中小型企业和本地商家使用，快速优化同城流量与搜索排名，解决"曝光低、客户引不来"的核心痛点'}
            onButtonClick={onButtonClick}
          >
            <OfferList text="✅ 生成式引擎优化.GEO" status="active" />
            <OfferList text="✅ 同城GEO全案配置" status="active" />
            <OfferList text="✅ 地图/本地流量优化" status="active" />
            <OfferList text="✅ 月度优化数据报表" status="active" />
            <OfferList text="✅ 7×12小时微信支持" status="active" />
            <OfferList text="✅ 1年访问与更新权限" status="active" />
          </PricingBox>
          <PricingBox
            packageName="个人定制全案·高级版"
            price={isMonthly ? "5999" : "71999"}
            duration={isMonthly ? "月" : "年"}
            subtitle={'适合大型企业与品牌定制，解决"流量瓶颈、增长停滞"的核心痛点'}
            onButtonClick={onButtonClick}
          >
            <OfferList text="✅ 全渠道生成式引擎优化" status="active" />
            <OfferList text="✅ 品牌级同城GEO战略" status="active" />
            <OfferList text="✅ 私域流量闭环搭建" status="active" />
            <OfferList text="✅ 季度深度增长报告" status="active" />
            <OfferList text="✅ 7×24小时专属运营支持" status="active" />
            <OfferList text="✅ 1年全案服务与升级权限" status="active" />
          </PricingBox>
        </div>
      </div>

      <div className="absolute bottom-0 left-0 z-[-1]">
        <svg
          width="239"
          height="601"
          viewBox="0 0 239 601"
          fill="none"
          xmlns="http://www.w3.org/2000/svg"
        >
          <rect
            opacity="0.3"
            x="-184.451"
            y="600.973"
            width="196"
            height="541.607"
            rx="2"
            transform="rotate(-128.7 -184.451 600.973)"
            fill="url(#paint0_linear_93:235)"
          />
          <rect
            opacity="0.3"
            x="-188.201"
            y="385.272"
            width="59.7544"
            height="541.607"
            rx="2"
            transform="rotate(-128.7 -188.201 385.272)"
            fill="url(#paint1_linear_93:235)"
          />
          <defs>
            <linearGradient
              id="paint0_linear_93:235"
              x1="-90.1184"
              y1="420.414"
              x2="-90.1184"
              y2="1131.65"
              gradientUnits="userSpaceOnUse"
            >
              <stop stopColor="#4A6CF7" />
              <stop offset="1" stopColor="#4A6CF7" stopOpacity="0" />
            </linearGradient>
            <linearGradient
              id="paint1_linear_93:235"
              x1="-159.441"
              y1="204.714"
              x2="-159.441"
              y2="915.952"
              gradientUnits="userSpaceOnUse"
            >
              <stop stopColor="#4A6CF7" />
              <stop offset="1" stopColor="#4A6CF7" stopOpacity="0" />
            </linearGradient>
          </defs>
        </svg>
      </div>
    </section>
  );
};

export default Pricing;