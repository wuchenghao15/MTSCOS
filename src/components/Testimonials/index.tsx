"use client"

import { cn } from "@/lib/utils"
import { Marquee } from "@/components/ui/marquee"
import { AuroraText } from "@/components/ui/aurora-text"
import { useState } from "react"
import { useAnimationControl } from "@/hooks/useAnimationControl"

const reviews = [
  {
    name: "刘老板",
    username: "@文海星辰-刘老板",
    body: "以前周边养猫的都不知道我家，做了GEO优化后，搜「武昌24小时宠物医院」，我们直接排首页前三！",
    img: "https://avatar.vercel.sh/pet"
  },
  {
    name: "陈姐",
    username: "@文海星辰-陈姐",
    body: "别家美甲都在卷价格，我做了AI搜索优化，现在问「光谷哪里做美甲好」，系统直接推荐我家，客单价高了！",
    img: "https://avatar.vercel.sh/nail"
  },
  {
    name: "张师傅",
    username: "@文海星辰-张师傅",
    body: "开锁这行全靠急单，优化后只要有人问AI「汉阳附近急开锁」，第一个弹出的就是我的电话，接单接到手软。",
    img: "https://avatar.vercel.sh/lock"
  },
  {
    name: "芳芳",
    username: "@文海星辰-芳芳",
    body: "这条街餐厅十几家，自从做了GEO，周末饭点翻台率涨了40%，都是搜「江汉路必吃火锅」找来的新客。",
    img: "https://avatar.vercel.sh/hotpot"
  },
  {
    name: "老周",
    username: "@文海星辰-老周",
    img: "https://avatar.vercel.sh/deco",
    body: "以前接活全靠蹲小区，现在业主问AI「武汉靠谱的装修工长」，我能排在推荐位，签单成功率翻倍。"
  },
  {
    name: "Linda",
    username: "@文海星辰-Linda",
    body: "瑜伽馆太多留不住人，做了本地搜索优化后，精准捕获了周边3公里想减肥的白领，续卡率提升了不少。",
    img: "https://avatar.vercel.sh/yoga"
  },
  {
    name: "大伟",
    username: "@文海星辰-大伟",
    body: "驾校竞争太激烈，优化后只要搜「洪山拿证快的驾校」，我家信息置顶展示，咨询量比上个月多了两倍。",
    img: "https://avatar.vercel.sh/car"
  },
  {
    name: "吴律师",
    username: "@文海星辰-吴律师",
    body: "法律服务看不见摸不着，做了GEO后，企业主搜「武汉合同纠纷律师」，我的专业介绍直接展现，案源稳了。",
    img: "https://avatar.vercel.sh/law"
  },
  {
    name: "强哥",
    username: "@文海星辰-强哥",
    body: "做建材批发太依赖老客，优化后现在搜「武汉批发瓷砖哪里便宜」，我的店铺信息全展示，新客占比涨了60%。",
    img: "https://avatar.vercel.sh/brick"
  },
  {
    name: "阿杰",
    username: "@文海星辰-阿杰",
    body: "以前只会修手机，现在做了AI优化，客户问「街道口上门修电脑」，我也能接到单，业务范围扩大了一圈。",
    img: "https://avatar.vercel.sh/pc"
  },
  {
    name: "苏苏",
    username: "@文海星辰-苏苏",
    body: "鲜花这东西时效性强，做了同城GEO，现在搜「武汉送花上门」，我的店总是靠前，情人节直接爆单！",
    img: "https://avatar.vercel.sh/flower"
  },
  {
    name: "老赵",
    username: "@文海星辰-老赵",
    body: "二手车水深信任难建立，优化后我的实拍视频和车源在AI搜索里展示，客户还没到店就先信了我三分。",
    img: "https://avatar.vercel.sh/car2"
  },
  {
    name: "Cici",
    username: "@文海星辰-Cici",
    body: "拍照好看但没人知道，做了GEO优化后，搜「武汉写真哪家好」，我的客片直接展示在前面，约拍排到下个月了。",
    img: "https://avatar.vercel.sh/photo"
  },
  {
    name: "阿文",
    username: "@文海星辰-阿文",
    body: "做短视频剪辑全靠接散单，优化后企业主搜「武汉视频制作公司」，我排在第一页，现在开始接企业年包了。",
    img: "https://avatar.vercel.sh/video"
  },
  {
    name: "林先生",
    username: "@文海星辰-林先生",
    body: "财税服务太抽象，做了本地搜索优化，创业者搜「武汉公司注册代办」，我的专业解读直接呈现，咨询精准多了。",
    img: "https://avatar.vercel.sh/money"
  },
  {
    name: "曼姐",
    username: "@文海星辰-曼姐",
    body: "民宿位置偏不好找，优化后游客问AI「武汉性价比高的民宿」，我的房源信息置顶，入住率提高了35%。",
    img: "https://avatar.vercel.sh/house"
  }
]

const firstRow = reviews.slice(0, 4)
const secondRow = reviews.slice(4, 8)
const thirdRow = reviews.slice(8, 12)
const fourthRow = reviews.slice(12, 16)

const ReviewCard = ({
  img,
  name,
  username,
  body,
}: {
  img: string
  name: string
  username: string
  body: string
}) => {
  return (
    <figure
      className={cn(
        "relative h-full w-fit cursor-pointer overflow-hidden rounded-xl border p-4 sm:w-36",
        "border-gray-950/[.1] bg-gray-950/[.01] hover:bg-gray-950/[.05]",
        "dark:border-gray-50/[.1] dark:bg-gray-50/[.10] dark:hover:bg-gray-50/[.15]",
        "will-change-transform"
      )}
    >
      <div className="flex flex-row items-center gap-2">
        <img className="rounded-full" width="32" height="32" alt={name} src={img} />
        <div className="flex flex-col">
          <figcaption className="text-sm font-medium dark:text-white">
            <AuroraText
              colors={["#ff2975", "#7928CA", "#0070F3", "#38bdf8"]}
              speed={1.2}
            >
              {name}
            </AuroraText>
          </figcaption>
          <p className="text-xs font-medium dark:text-white/40">
            <AuroraText
              colors={["#ff2975", "#7928CA", "#0070F3", "#38bdf8"]}
              speed={1.2}
            >
              {username}
            </AuroraText>
          </p>
        </div>
      </div>
      <blockquote className="mt-2 text-sm">{body}</blockquote>
    </figure>
  )
}

export function Marquee3D() {
  const [isPaused, setIsPaused] = useState(false)
  const { ref: observerRef, shouldAnimate } = useAnimationControl<HTMLDivElement>({
    rootMargin: "100px",
    threshold: 0.1,
  })

  const handleMouseEnter = () => setIsPaused(true)
  const handleMouseLeave = () => setIsPaused(false)

  const isAnimationPaused = isPaused || !shouldAnimate

  return (
    <div 
      ref={observerRef}
      className="relative flex h-96 w-full flex-row items-center justify-center gap-4 overflow-hidden [perspective:300px] cursor-pointer content-visibility-auto"
      onMouseEnter={handleMouseEnter}
      onMouseLeave={handleMouseLeave}
    >
      <div
        className="flex flex-row items-center gap-4"
        style={{
          transform:
            "translateX(-100px) translateY(0px) translateZ(-100px) rotateX(20deg) rotateY(-10deg) rotateZ(20deg)",
          willChange: "transform",
        }}
      >
        <Marquee paused={isAnimationPaused} vertical className="[--duration:20s]">
          {firstRow.map((review) => (
            <ReviewCard key={review.username} {...review} />
          ))}
        </Marquee>
        <Marquee reverse paused={isAnimationPaused} className="[--duration:20s]" vertical>
          {secondRow.map((review) => (
            <ReviewCard key={review.username} {...review} />
          ))}
        </Marquee>
        <Marquee reverse paused={isAnimationPaused} className="[--duration:20s]" vertical>
          {thirdRow.map((review) => (
            <ReviewCard key={review.username} {...review} />
          ))}
        </Marquee>
        <Marquee paused={isAnimationPaused} className="[--duration:20s]" vertical>
          {fourthRow.map((review) => (
            <ReviewCard key={review.username} {...review} />
          ))}
        </Marquee>
      </div>

      <div className="from-background pointer-events-none absolute inset-x-0 top-0 h-1/4 bg-gradient-to-b"></div>
      <div className="from-background pointer-events-none absolute inset-x-0 bottom-0 h-1/4 bg-gradient-to-t"></div>
      <div className="from-background pointer-events-none absolute inset-y-0 left-0 w-1/4 bg-gradient-to-r"></div>
      <div className="from-background pointer-events-none absolute inset-y-0 right-0 w-1/4 bg-gradient-to-l"></div>
    </div>
  )
}

export default function Testimonials() {
  return (
    <>
      <section className="dark:bg-bg-color-dark bg-white pb-16 md:pb-20 lg:pb-28">
        <div className="container">
          <div className="mx-auto mb-[100px] max-w-[665px] text-center">
            <h2 className="mb-4 text-3xl font-bold leading-tight! text-black dark:text-white sm:text-4xl md:text-[45px]">
              <AuroraText
                colors={["#ff2975", "#7928CA", "#0070F3", "#38bdf8"]}
                speed={1.2}
              >
                生成式引擎优化.GEO
              </AuroraText>
            </h2>
            <p className="text-base leading-relaxed! text-body-color md:text-lg">
             听听他们如何通过 GEO 获取同城精准客流。
            </p>
          </div>
        </div>
        <Marquee3D />
      </section>
    </>
  )
}