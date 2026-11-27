/**
 * Note: Use position fixed according to your needs
 * Desktop navbar is better positioned at the bottom
 * Mobile navbar is better positioned at bottom right.
 **/

import {cn} from '@/lib/utils';
import {withBasePath} from '@/lib/base-path';
import {splitByGroup} from '@/lib/dock-groups';
import {findActiveHref} from '@/lib/dock-active';
import {IconLayoutNavbarCollapse} from '@tabler/icons-react';
import {
  AnimatePresence,
  MotionValue,
  motion,
  useMotionValue,
  useTransform,
} from 'motion/react';

import {Fragment, useRef, useState, memo, useCallback} from 'react';

export type FloatingDockItem = {
  title: string;
  icon: React.ReactNode;
  href?: string;
  onClick?: () => void;
  tooltip?: string;
  customComponent?: React.ReactNode;
  external?: boolean;
  /** 分组键：相邻两项不同时，两组之间画一条分隔线（见 `@/lib/dock-groups`）。 */
  groupKey?: string;
  /** 分组名（已翻译）。桌面端挂在分隔线上做 hover 提示，移动端直接显示。 */
  groupLabel?: string;
};

export const FloatingDock = ({
  items,
  desktopClassName,
  mobileClassName,
  mobileButtonClassName,
  pathname,
}: {
  items: FloatingDockItem[];
  desktopClassName?: string;
  mobileClassName?: string;
  mobileButtonClassName?: string;
  /** 来自 usePathname()，用于当前页高亮判定。 */
  pathname?: string | null;
}) => {
  // 当前页在**这里**算一次，再把结果传下去：两个子组件各自逐项判断的话，
  // /settings/models 会让「设置」和「模型」同时亮（见 lib/dock-active.ts 第 4 条）。
  const activeHref = findActiveHref(
      items.filter((i) => !i.customComponent && !i.external).map((i) => i.href),
      pathname,
  );
  return (
    <>
      <FloatingDockDesktop items={items} className={desktopClassName} activeHref={activeHref} />
      <FloatingDockMobile
        items={items}
        className={mobileClassName}
        buttonClassName={mobileButtonClassName}
        activeHref={activeHref}
      />
    </>
  );
};

const FloatingDockMobile = memo(
    ({
      items,
      className,
      buttonClassName,
      activeHref,
    }: {
    items: FloatingDockItem[];
    className?: string;
    buttonClassName?: string;
    activeHref?: string | null;
  }) => {
      const [open, setOpen] = useState(false);

      const toggleOpen = useCallback(() => {
        setOpen((prev) => !prev);
      }, []);

      return (
        <div className={cn('relative block md:hidden', className)}>
          <AnimatePresence>
            {open && (
              <motion.div
                layoutId="nav"
                className="absolute bottom-full right-0 mb-2 flex max-h-[min(70dvh,420px)] w-max min-w-[4.5rem] flex-col items-stretch gap-1 overflow-y-auto p-0.5"
              >
                {/*
                  手机端也要分组。原来这里是 `if (item.title === 'divider') return null`
                  —— 分隔线被跳过后，手机上 11 项平铺，分组语义完全消失（P1-1）。
                  现在改成按 groupKey 切，并在交界处画一条**带组名**的横线。
                */}
                {(() => {
                  const groups = splitByGroup(items);
                  const total = items.length;
                  let flatIndex = -1;
                  return groups.map((group, groupIndex) => (
                    <Fragment key={group.key || `group-${groupIndex}`}>
                      {groupIndex > 0 && (
                        <div
                          data-slot="dock-group-separator"
                          className="flex flex-col items-center gap-1 pt-1"
                        >
                          <span className="h-px w-5 bg-border" />
                          {group.label ? (
                            <span className="text-[0.5625rem] leading-none text-muted-foreground">
                              {group.label}
                            </span>
                          ) : null}
                        </div>
                      )}
                      {group.items.map((item) => {
                        flatIndex += 1;
                        const idx = flatIndex;
                        const isActive = !item.customComponent && !!activeHref && item.href === activeHref;
                        return (
                          <motion.div
                            key={item.title}
                            initial={{opacity: 0, y: 10}}
                            animate={{
                              opacity: 1,
                              y: 0,
                            }}
                            exit={{
                              opacity: 0,
                              y: 10,
                              transition: {
                                delay: idx * 0.05,
                              },
                            }}
                            transition={{delay: (total - 1 - idx) * 0.05}}
                          >
                            {item.customComponent ? (
                              <div
                                className={cn(
                                    'flex min-h-[2rem] min-w-[2rem] items-center justify-center rounded-full bg-gray-50 dark:bg-neutral-900',
                                    buttonClassName,
                                    // 菜单项按文字撑开：buttonClassName 的 h-10 w-10 是给底部圆形按钮的，原样套上会把文字截断
                                    // 快速添加 / 个人信息内部自带 px-3，外层不再叠加左右内边距
                                    'h-10 w-full px-0',
                                )}
                              >
                                {item.customComponent}
                              </div>
                            ) : item.href ? (
                            <a
                              href={withBasePath(item.href)}
                              aria-label={item.title}
                              {...(isActive ? {'aria-current': 'page' as const} : {})}
                              className={cn(
                                  'flex h-9 items-center justify-center rounded-full bg-gray-50 px-3 dark:bg-neutral-900',
                                  buttonClassName,
                                  // 菜单项按文字撑开：buttonClassName 的 h-10 w-10 是给底部圆形按钮的，原样套上会把文字截断
                                  'h-10 w-full px-3',
                                  // 高亮必须排在 buttonClassName 之后：那里带着 bg-background/70，
                                  // twMerge 是后写的赢，排在前面高亮色会被它盖掉
                                  isActive && 'border-foreground bg-foreground dark:bg-foreground',
                              )}
                              {...((item.external || item.href.startsWith('https://')) ?
                                {target: '_blank', rel: 'noopener noreferrer'} :
                                {})}
                            >
                              <span className={cn(
                                'text-sm font-medium whitespace-nowrap',
                                isActive ? 'text-background dark:text-background' : 'text-foreground',
                              )}>
                                {item.title}
                              </span>
                            </a>
                          ) : (
                            <button
                              onClick={item.onClick}
                              aria-label={item.title}
                              className={cn(
                                  'flex h-9 items-center justify-center rounded-full bg-gray-50 px-3 dark:bg-neutral-900',
                                  buttonClassName,
                                  // 菜单项按文字撑开：buttonClassName 的 h-10 w-10 是给底部圆形按钮的，原样套上会把文字截断
                                  'h-10 w-full px-3',
                              )}
                            >
                              <span className="text-sm font-medium text-foreground whitespace-nowrap">
                                {item.title}
                              </span>
                            </button>
                          )}
                          </motion.div>
                        );
                      })}
                    </Fragment>
                  ));
                })()}
              </motion.div>
            )}
          </AnimatePresence>
          <button
            data-slot="dock-mobile-toggle"
            aria-label={open ? 'collapse navigation' : 'expand navigation'}
            aria-expanded={open}
            onClick={toggleOpen}
            className={cn(
                'flex h-8 w-8 items-center justify-center rounded-full bg-gray-50 dark:bg-neutral-800',
                buttonClassName,
            )}
          >
            <motion.div
              animate={{rotate: open ? 180 : 0}}
              transition={{duration: 0.3, ease: 'easeInOut'}}
            >
              <IconLayoutNavbarCollapse className="h-4 w-4 text-neutral-500 dark:text-neutral-400" />
            </motion.div>
          </button>
        </div>
      );
    },
);

FloatingDockMobile.displayName = 'FloatingDockMobile';

/**
 * 分隔线的「命中区」半宽（px）。
 *
 * 为什么要留宽、而且**不能**靠分隔线自己的 hover 事件：
 *
 * 底栏是会放大的——鼠标一动，附近的图标就从 40px 长到 70px，整个底栏随之变宽
 * （实测 725 → 787px）。底栏是 `translateX(-50%)` 居中的，于是**分隔线会从光标
 * 底下挪走**（实测挪 8~30px，而线本身只有 1px 宽 + 8px 内边距）。用
 * `onMouseEnter`/`onMouseLeave` 的结果是「组名亮一下又灭」：用户在界面上看到的
 * 是一次闪烁，而代码里看不出任何异常。
 *
 * 所以判据改成在底栏的 mousemove 里**当场量**每条分隔线的矩形，看光标落在谁的
 * 命中区里。光标不动、只有布局在动时不会再触发 mousemove，标签就留在屏幕上——
 * 这正是想要的：它是「我把鼠标放上去了」的反馈，不该被图标放大挤掉。
 */
const DIVIDER_HIT_SLOP = 10;

const FloatingDockDesktop = memo(
    ({
      items,
      className,
      activeHref,
    }: {
    items: FloatingDockItem[];
    className?: string;
    activeHref?: string | null;
  }) => {
      const mouseX = useMotionValue(Infinity);
      const rootRef = useRef<HTMLDivElement>(null);
      const [activeDivider, setActiveDivider] = useState<number | null>(null);

      const handleMouseMove = useCallback(
          (e: React.MouseEvent) => {
            mouseX.set(e.pageX);

            const nodes =
              rootRef.current?.querySelectorAll('[data-slot=dock-group-divider]');
            let next: number | null = null;
            if (nodes) {
              for (let i = 0; i < nodes.length; i += 1) {
                const rect = nodes[i].getBoundingClientRect();
                if (e.clientX >= rect.left - DIVIDER_HIT_SLOP &&
                    e.clientX <= rect.right + DIVIDER_HIT_SLOP) {
                  next = i;
                  break;
                }
              }
            }
            // 值没变时 React 会跳过重渲染，所以这里可以放心每次 mousemove 都设。
            setActiveDivider(next);
          },
          [mouseX],
      );

      const handleMouseLeave = useCallback(() => {
        mouseX.set(Infinity);
        setActiveDivider(null);
      }, [mouseX]);

      return (
        <motion.div
          ref={rootRef}
          onMouseMove={handleMouseMove}
          onMouseLeave={handleMouseLeave}
          className={cn(
              'mx-auto hidden items-center gap-1 rounded-xl bg-gray-50 px-2 py-1.5 md:flex dark:bg-neutral-900',
              className,
          )}
        >
          {(() => {
            const groups = splitByGroup(items);

            return (
              <>
                {groups.map((group, index) => (
                  <Fragment key={group.key || `group-${index}`}>
                    {/* `activeDivider` 数的是**分隔线**在 DOM 里的序号，而这里只有
                        `index > 0` 的组才画线（第一组之前没有线），所以是 index - 1。 */}
                    {index > 0 &&
                      <GroupDivider label={group.label} active={activeDivider === index - 1} />}
                    <div className="flex items-end gap-2">
                      {group.items.map((item) => (
                        <IconContainer mouseX={mouseX} key={item.title} activeHref={activeHref} {...item} />
                      ))}
                    </div>
                  </Fragment>
                ))}
              </>
            );
          })()}
        </motion.div>
      );
    },
);

FloatingDockDesktop.displayName = 'FloatingDockDesktop';

/**
 * 组间分隔线。光标靠近时在线的上方显示组名。
 *
 * ⚠️ `active` 由**父组件按光标位置算**，本组件刻意不带自己的 hover 状态——理由见
 * `DIVIDER_HIT_SLOP` 上面那段（元素会被图标放大推走）。
 */
const GroupDivider = memo(({label, active}: {label?: string; active: boolean}) => {
  return (
    <div
      data-slot="dock-group-divider"
      className="relative flex items-center justify-center px-1 mx-1 self-stretch"
    >
      <div className="w-px h-full bg-border"></div>
      <AnimatePresence>
        {active && label ? (
          <motion.div
            initial={{opacity: 0, y: 10, x: '-50%'}}
            animate={{opacity: 1, y: 0, x: '-50%'}}
            exit={{opacity: 0, y: 2, x: '-50%'}}
            className="absolute -top-8 left-1/2 w-fit whitespace-nowrap rounded-md border border-gray-200 bg-gray-100 px-2 py-0.5 text-xs text-neutral-700 dark:border-neutral-900 dark:bg-neutral-800 dark:text-white"
          >
            {label}
          </motion.div>
        ) : null}
      </AnimatePresence>
    </div>
  );
});

GroupDivider.displayName = 'GroupDivider';

/**
 * 文字标签导航按钮（桌面端 Dock 的每一项）。
 *
 * 高亮样式：bg-foreground text-background（深浅色主题均清晰）。
 * hover 时：非激活项变浅灰；激活项保持 bg-foreground，hover 加深至 bg-foreground/85。
 * 字号与高度都以 rem 计，跟随根字号（设置 → 界面 → 字号）等比缩放。
 */
const IconContainer = memo(
    ({
      mouseX,
      title,
      href,
      onClick,
      customComponent,
      external,
      activeHref,
    }: FloatingDockItem & {mouseX: MotionValue; activeHref?: string | null}) => {
      const ref = useRef<HTMLDivElement>(null);

      // 保留 mouseX 追踪：FloatingDockDesktop 仍需要知道鼠标位置以判断分隔线高亮
      const distance = useTransform(mouseX, (val) => {
        const bounds = ref.current?.getBoundingClientRect() ?? {x: 0, width: 0};
        return val - bounds.x - bounds.width / 2;
      });

      // 文字标签不再做放大动画（放大会让布局跳动、文字溢出），用细腻的背景色过渡代替
      void distance; // 保留依赖，避免 Tree-shaking 警告

      const [hovered, setHovered] = useState(false);

      const handleMouseEnter = useCallback(() => setHovered(true), []);
      const handleMouseLeave = useCallback(() => setHovered(false), []);

      // customComponent（Quick add / Profile）不参与当前页判定
      const isActive = !customComponent && !!activeHref && href === activeHref;

      const Element = customComponent ? 'div' : href ? 'a' : 'button';
      const elementProps = customComponent ? {} : href ?
        {
          // 原生 <a> 不经过 next/link，basePath 不会自动生效
          href: withBasePath(href),
          'aria-label': title,
          ...(isActive ? {'aria-current': 'page' as const} : {}),
          ...((external || href.startsWith('https://')) ?
            {target: '_blank', rel: 'noopener noreferrer'} :
            {}),
        } :
        {onClick, 'aria-label': title};

      return (
        <Element {...elementProps}>
          <div
            ref={ref}
            onMouseEnter={handleMouseEnter}
            onMouseLeave={handleMouseLeave}
            className={cn(
              'flex h-8 cursor-pointer items-center justify-center rounded-full px-3 transition-colors',
              isActive
                ? hovered
                  ? 'bg-foreground/85 dark:bg-foreground/85'
                  : 'bg-foreground dark:bg-foreground'
                : hovered
                  ? 'bg-gray-200 dark:bg-neutral-700'
                  : 'bg-transparent',
            )}
          >
            {customComponent ? (
              // customComponent 由 ManagementBar 提供，内部已改为文字
              customComponent
            ) : (
              <span className={cn(
                'text-xs font-medium whitespace-nowrap leading-none',
                isActive ? 'text-background dark:text-background' : 'text-foreground',
              )}>
                {title}
              </span>
            )}
          </div>
        </Element>
      );
    },
);

IconContainer.displayName = 'IconContainer';
