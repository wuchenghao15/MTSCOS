"use client"

import { cn } from "@/lib/utils"
import { Marquee } from "@/components/ui/marquee"
import { AuroraText } from "@/components/ui/aurora-text"
import { useState, useEffect } from "react"
import { useAnimationControl } from "@/hooks/useAnimationControl"

type Review = {
  name: string
  username: string
  body: string
  img: string
}

const reviews: Review[] = [
  {
    name: "刘老板",
    username: "",
    body: "以前周边养猫的都不知道我家，现在人家搜\"武昌24小时宠物医院\"，直接就能找到我们，半夜急诊的单都多了不少。",
    img: "https://avatar.vercel.sh/pet"
  },
  {
    name: "陈姐",
    username: "",
    body: "以前大家都在卷低价，我这边客单价一直上不去。现在很多人问\"光谷哪里做美甲好\"，都能刷到我家，做的款式也都是客单价高的，不用再打价格战了。",
    img: "https://avatar.vercel.sh/nail"
  },
  {
    name: "张师傅",
    username: "",
    body: "开锁全靠急单，以前都是老客户介绍。现在有人搜\"汉阳附近急开锁\"，第一个就能看到我电话，半夜都能接到单，忙不过来。",
    img: "https://avatar.vercel.sh/lock"
  },
  {
    name: "芳芳",
    username: "",
    body: "这条街十几家火锅店，以前周末饭点都要靠发传单拉客。现在很多人搜\"江汉路必吃火锅\"都能找到我们，翻台率直接涨了近一半，忙都忙不过来。",
    img: "https://avatar.vercel.sh/hotpot"
  },
  {
    name: "老周",
    username: "",
    img: "https://avatar.vercel.sh/deco",
    body: "以前只能蹲小区门口碰运气接活，现在业主搜\"武汉靠谱的装修工长\"，能直接看到我的案例，很多人加我微信，签单率比以前高太多了。"
  },
  {
    name: "Linda",
    username: "",
    body: "周边瑜伽馆太多，一直留不住人。现在很多住在附近的白领想减肥，搜瑜伽馆就能找到我家，很多人直接办了长期卡，续卡率高了不少。",
    img: "https://avatar.vercel.sh/yoga"
  },
  {
    name: "大伟",
    username: "",
    body: "驾校太多了，一直愁招生。现在人家搜\"洪山拿证快的驾校\"，能直接看到我家，咨询的人比上个月多了两倍，都快忙不过来了。",
    img: "https://avatar.vercel.sh/car"
  },
  {
    name: "吴律师",
    username: "",
    body: "以前都是熟人介绍，案源一直不稳定。现在企业老板搜\"武汉合同纠纷律师\"，能看到我的案例和介绍，很多人主动找过来，案子不用愁了。",
    img: "https://avatar.vercel.sh/law"
  },
  {
    name: "强哥",
    username: "",
    body: "以前全靠老客户介绍，一直没有新客源。现在很多人搜\"武汉批发瓷砖哪里便宜\"，都能找到我家，新客户占比直接涨了一大半，生意稳多了。",
    img: "https://avatar.vercel.sh/brick"
  },
  {
    name: "阿杰",
    username: "",
    body: "以前只会修手机，生意很局限。现在有人问\"街道口上门修电脑\"，也能找到我，不光能修手机，电脑维修的单也接了不少，业务范围一下子就大了。",
    img: "https://avatar.vercel.sh/pc"
  },
  {
    name: "苏苏",
    username: "",
    body: "鲜花这东西靠的就是时效，以前节日都要靠发朋友圈。现在搜\"武汉送花上门\"，我家总能排在前面，情人节直接爆单，忙到凌晨都没停。",
    img: "https://avatar.vercel.sh/flower"
  },
  {
    name: "老赵",
    username: "",
    body: "二手车行业信任难建立，很多人都怕被坑。现在客户搜车源，能直接看到我的实拍视频和车源，很多人还没到店就已经很信任我了，成交率高了不少。",
    img: "https://avatar.vercel.sh/car2"
  },
  {
    name: "Cici",
    username: "",
    body: "拍了很多好看的客片，但一直没人知道。现在人家搜\"武汉写真哪家好\"，能直接看到我的作品，约拍都排到下个月了，不用再靠低价引流了。",
    img: "https://avatar.vercel.sh/photo"
  },
  {
    name: "阿文",
    username: "",
    body: "以前全靠接散单，价格压得很低，还不稳定。现在企业老板搜\"武汉视频制作公司\"，能直接找到我，现在已经开始接企业年包了，收入稳多了。",
    img: "https://avatar.vercel.sh/video"
  },
  {
    name: "林先生",
    username: "",
    body: "财税服务看不见摸不着，一直很难让客户信任。现在创业者搜\"武汉公司注册代办\"，能看到我的专业解读，来咨询的客户都很精准，很多人直接就签了。",
    img: "https://avatar.vercel.sh/money"
  },
  {
    name: "曼姐",
    username: "",
    body: "民宿位置有点偏，很多游客找不到。现在人家问\"武汉性价比高的民宿\"，能直接看到我的房源，入住率一下子就提上来了，比之前高了三分之一还多。",
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
  onClick,
  onImageClick,
}: {
  img: string
  name: string
  username: string
  body: string
  onClick?: () => void
  onImageClick?: () => void
}) => {
  return (
    <figure
      onClick={onClick}
      className={cn(
        "relative cursor-pointer overflow-hidden border",
        "border-gray-950/[.1] bg-gray-950/[.01] hover:bg-gray-950/[.05]",
        "dark:border-gray-50/[.1] dark:bg-gray-50/[.10] dark:hover:bg-gray-50/[.15]",
        "md:rounded-[12px] md:p-4 md:min-w-[200px] md:max-w-[280px] md:min-h-[180px]",
        "rounded-[16px] p-5 min-w-[calc(50vw-32px)] max-w-[calc(50vw-32px)] min-h-[200px]"
      )}
    >
      <div className="flex flex-row items-center gap-2 md:gap-2 gap-3">
        <img 
          onClick={(e) => {
            e.stopPropagation()
            onImageClick?.()
          }}
          className="rounded-full md:w-8 md:h-8 w-10 h-10 cursor-pointer hover:ring-2 hover:ring-blue-500 transition-all" 
          alt={name} 
          src={img} 
        />
        <div className="flex flex-col md:gap-0 gap-1">
          <figcaption className="font-medium dark:text-white md:text-sm text-[13px]">
            <AuroraText
              colors={["#ff2975", "#7928CA", "#0070F3", "#38bdf8"]}
              speed={1.2}
            >
              {name}
            </AuroraText>
          </figcaption>
          <p className="font-medium dark:text-white/40 md:text-xs text-[11px]">
            <AuroraText
              colors={["#ff2975", "#7928CA", "#0070F3", "#38bdf8"]}
              speed={1.2}
            >
              {username}
            </AuroraText>
          </p>
        </div>
      </div>
      <blockquote className="md:mt-2 mt-3 md:text-sm md:leading-normal md:line-clamp-3 text-[12px] leading-[1.5] line-clamp-4">{body}</blockquote>
    </figure>
  )
}

export function Marquee3D() {
  const [modalReview, setModalReview] = useState<Review | null>(null)
  const [imageModalSrc, setImageModalSrc] = useState<string | null>(null)
  const { ref: observerRef, shouldAnimate } = useAnimationControl<HTMLDivElement>({
    rootMargin: "100px",
    threshold: 0.1,
  })

  const isModalOpen = modalReview !== null || imageModalSrc !== null
  const isAnimationPaused = !shouldAnimate || isModalOpen

  const mobileFirstRow = reviews.slice(0, 8)
  const mobileSecondRow = reviews.slice(8, 16)

  useEffect(() => {
    if (isModalOpen) {
      document.body.style.overflow = "hidden"
    } else {
      document.body.style.overflow = ""
    }
    return () => {
      document.body.style.overflow = ""
    }
  }, [isModalOpen])

  const handleImageClick = (imgSrc: string) => setImageModalSrc(imgSrc)
  const closeImageModal = () => setImageModalSrc(null)
  const closeReviewModal = () => setModalReview(null)

  return (
    <div 
      ref={observerRef}
      className="relative flex h-96 w-full flex-row items-center justify-center gap-4 overflow-x-hidden overflow-y-hidden cursor-pointer content-visibility-auto"
    >
      {/* PC端：4列布局 */}
      <div className="hidden md:flex flex-row items-center gap-4">
        <Marquee paused={isAnimationPaused} vertical repeat={2} className="[--duration:20s]">
          {firstRow.map((review, index) => (
            <ReviewCard key={index} {...review} onClick={() => setModalReview(review)} onImageClick={() => handleImageClick(review.img)} />
          ))}
        </Marquee>
        <Marquee reverse paused={isAnimationPaused} repeat={2} className="[--duration:20s]" vertical>
          {secondRow.map((review, index) => (
            <ReviewCard key={index} {...review} onClick={() => setModalReview(review)} onImageClick={() => handleImageClick(review.img)} />
          ))}
        </Marquee>
        <Marquee reverse paused={isAnimationPaused} repeat={2} className="[--duration:20s]" vertical>
          {thirdRow.map((review, index) => (
            <ReviewCard key={index} {...review} onClick={() => setModalReview(review)} onImageClick={() => handleImageClick(review.img)} />
          ))}
        </Marquee>
        <Marquee paused={isAnimationPaused} repeat={2} className="[--duration:20s]" vertical>
          {fourthRow.map((review, index) => (
            <ReviewCard key={index} {...review} onClick={() => setModalReview(review)} onImageClick={() => handleImageClick(review.img)} />
          ))}
        </Marquee>
      </div>

      {/* 移动端：2列布局，全部16张卡片 */}
      <div className="flex md:hidden flex-row items-center justify-center gap-3 w-full px-3">
        <Marquee paused={isAnimationPaused} vertical repeat={2} className="[--duration:30s]">
          {mobileFirstRow.map((review, index) => (
            <ReviewCard key={index} {...review} onClick={() => setModalReview(review)} onImageClick={() => handleImageClick(review.img)} />
          ))}
        </Marquee>
        <Marquee reverse paused={isAnimationPaused} repeat={2} className="[--duration:30s]" vertical>
          {mobileSecondRow.map((review, index) => (
            <ReviewCard key={index} {...review} onClick={() => setModalReview(review)} onImageClick={() => handleImageClick(review.img)} />
          ))}
        </Marquee>
      </div>

      {/* PC端渐变遮罩 */}
      <div className="from-background pointer-events-none absolute inset-x-0 top-0 h-1/4 bg-gradient-to-b hidden md:block"></div>
      <div className="from-background pointer-events-none absolute inset-x-0 bottom-0 h-1/4 bg-gradient-to-t hidden md:block"></div>
      <div className="from-background pointer-events-none absolute inset-y-0 left-0 w-1/4 bg-gradient-to-r hidden md:block"></div>
      <div className="from-background pointer-events-none absolute inset-y-0 right-0 w-1/4 bg-gradient-to-l hidden md:block"></div>

      {/* 文案弹窗 */}
      {modalReview && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm p-4"
          onClick={closeReviewModal}
        >
          <div
            className="relative w-full max-w-[90vw] md:max-w-[500px] rounded-[16px] md:rounded-[12px] border border-gray-950/[.1] dark:border-gray-50/[.1] bg-white dark:bg-gray-900 p-6 md:p-6 shadow-2xl overflow-y-auto max-h-[85vh]"
            onClick={(e) => e.stopPropagation()}
          >
            <button
              onClick={closeReviewModal}
              className="absolute top-3 right-3 w-8 h-8 flex items-center justify-center rounded-full bg-gray-100 dark:bg-gray-800 hover:bg-gray-200 dark:hover:bg-gray-700 transition-colors text-gray-500 dark:text-gray-400 text-lg font-bold"
              aria-label="关闭"
            >
              ×
            </button>
            <div className="flex flex-row items-center gap-3 pr-10 mb-4">
              <img className="rounded-full w-12 h-12" alt={modalReview.name} src={modalReview.img} />
              <div className="flex flex-col">
                <figcaption className="text-base font-medium dark:text-white">
                  <AuroraText
                    colors={["#ff2975", "#7928CA", "#0070F3", "#38bdf8"]}
                    speed={1.2}
                  >
                    {modalReview.name}
                  </AuroraText>
                </figcaption>
                {modalReview.username && (
                  <p className="text-sm font-medium dark:text-white/40">
                    <AuroraText
                      colors={["#ff2975", "#7928CA", "#0070F3", "#38bdf8"]}
                      speed={1.2}
                    >
                      {modalReview.username}
                    </AuroraText>
                  </p>
                )}
              </div>
            </div>
            <blockquote className="text-[15px] md:text-base leading-[1.6] text-gray-700 dark:text-gray-200">
              {modalReview.body}
            </blockquote>
          </div>
        </div>
      )}

      {/* 图片弹窗 */}
      {imageModalSrc && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/80 backdrop-blur-sm p-4"
          onClick={closeImageModal}
        >
          <div
            className="relative max-w-[90vw] max-h-[90vh]"
            onClick={(e) => e.stopPropagation()}
          >
            <button
              onClick={closeImageModal}
              className="absolute -top-10 right-0 w-8 h-8 flex items-center justify-center rounded-full bg-white/20 hover:bg-white/30 transition-colors text-white text-lg font-bold"
              aria-label="关闭"
            >
              ×
            </button>
            <img 
              src={imageModalSrc} 
              alt="头像原图"
              className="max-w-[90vw] max-h-[85vh] rounded-[12px] shadow-2xl"
            />
          </div>
        </div>
      )}
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
             听听他们如何通过GEO优化，解决同城获客难题，拿到稳定精准客源。
            </p>
          </div>
        </div>
        <Marquee3D />
      </section>
    </>
  )
}
