<?xml version="1.0" encoding="utf-8"?>
<!DOCTYPE TS>
<TS version="2.1" language="zh_CN">
<context>
    <name>MainWindow</name>
    <message>
        <location filename="../../gui/view/main_window.py" line="309"/>
        <source>Failed to save settings, reverted</source>
        <translation>保存失败，已恢复原设置</translation>
    </message>
    <message>
        <location filename="../../gui/view/main_window.py" line="391"/>
        <source>Sample</source>
        <translation>示例</translation>
    </message>
    <message>
        <location filename="../../gui/view/main_window.py" line="391"/>
        <source>Settings</source>
        <translation>设置</translation>
    </message>
    <message>
        <location filename="../../gui/view/main_window.py" line="107"/>
        <location filename="../../gui/view/main_window.py" line="389"/>
        <location filename="../../gui/view/main_window.py" line="393"/>
        <source>Sheep Box</source>
        <extracomment>导航条图标键：设置齿轮状滑块 / 示例页叠层。</extracomment>
        <translation>Sheep Box</translation>
    </message>
</context>
<context>
    <name>RegionPicker</name>
    <message>
        <location filename="../../gui/components/region_picker.py" line="156"/>
        <source>Click a window, or drag to select a region (Esc to cancel)</source>
        <translation>单击窗口选择整窗，或拖拽框选区域（Esc 取消）</translation>
    </message>
</context>
<context>
    <name>SamplePage</name>
    <message>
        <location filename="../../gui/view/sample_page.py" line="84"/>
        <source>Sample</source>
        <translation>示例</translation>
    </message>
    <message>
        <location filename="../../gui/view/sample_page.py" line="85"/>
        <source>A demo page for the tab navigation</source>
        <translation>用于验证标签导航的示例页</translation>
    </message>
    <message>
        <location filename="../../gui/view/sample_page.py" line="86"/>
        <source>Navigation</source>
        <translation>导航条</translation>
    </message>
    <message>
        <location filename="../../gui/view/sample_page.py" line="89"/>
        <source>The active page expands into a pill; inactive pages stay as icons and show their title on hover. When there are too many pages, page-turn arrows appear on both sides.</source>
        <translation>当前页展开为胶囊，其余页收缩为图标，鼠标悬停显示标题；页面过多时导航条两侧出现翻页箭头。</translation>
    </message>
</context>
<context>
    <name>SettingsTab</name>
    <message>
        <location filename="../../gui/view/settings_tab.py" line="294"/>
        <source>Appearance</source>
        <extracomment>可选刷新间隔（毫秒, 显示文本）。显示文本是数值单位，不参与翻译。 配置缺失时的兜底锚点（与 ``config.schema`` 默认值一致）</extracomment>
        <translation>外观</translation>
    </message>
    <message>
        <location filename="../../gui/view/settings_tab.py" line="295"/>
        <source>UI Language</source>
        <translation>界面语言</translation>
    </message>
    <message>
        <location filename="../../gui/view/settings_tab.py" line="296"/>
        <source>Theme</source>
        <translation>主题</translation>
    </message>
    <message>
        <location filename="../../gui/view/settings_tab.py" line="297"/>
        <source>Status Bar</source>
        <translation>状态栏</translation>
    </message>
    <message>
        <location filename="../../gui/view/settings_tab.py" line="298"/>
        <source>Refresh Interval</source>
        <translation>刷新间隔</translation>
    </message>
    <message>
        <location filename="../../gui/view/settings_tab.py" line="299"/>
        <source>Pressure Colors</source>
        <translation>压力着色</translation>
    </message>
    <message>
        <location filename="../../gui/view/settings_tab.py" line="303"/>
        <source>Light</source>
        <translation>浅色</translation>
    </message>
    <message>
        <location filename="../../gui/view/settings_tab.py" line="306"/>
        <source>Dark</source>
        <translation>深色</translation>
    </message>
</context>
<context>
    <name>StatusBar</name>
    <message>
        <location filename="../../gui/components/status_bar.py" line="190"/>
        <source>CPU</source>
        <extracomment>状态栏高度（含 1px 分隔线） 压力点直径 数值列宽度（容纳 &quot;100%&quot;） 指标之间的水平间距</extracomment>
        <translation>CPU</translation>
    </message>
    <message>
        <location filename="../../gui/components/status_bar.py" line="191"/>
        <source>MEM</source>
        <translation>内存</translation>
    </message>
    <message>
        <location filename="../../gui/components/status_bar.py" line="236"/>
        <source>GPU</source>
        <translation>GPU</translation>
    </message>
    <message>
        <location filename="../../gui/components/status_bar.py" line="238"/>
        <source>GPU %1</source>
        <translation>GPU %1</translation>
    </message>
</context>
<context>
    <name>WindowButton</name>
    <message>
        <location filename="../../gui/components/title_bar.py" line="91"/>
        <source>Close</source>
        <extracomment>标题栏高度（导航条 32 高 + 上下留白，与主流桌面应用一致）。 窗口按钮尺寸。 关闭键悬停底色（Windows 约定）。</extracomment>
        <translation>关闭</translation>
    </message>
    <message>
        <location filename="../../gui/components/title_bar.py" line="93"/>
        <source>Minimize</source>
        <translation>最小化</translation>
    </message>
    <message>
        <location filename="../../gui/components/title_bar.py" line="95"/>
        <source>Maximize</source>
        <translation>最大化</translation>
    </message>
    <message>
        <location filename="../../gui/components/title_bar.py" line="107"/>
        <source>Restore</source>
        <translation>还原</translation>
    </message>
</context>
<context>
    <name>_AnchorPopup</name>
    <message>
        <location filename="../../gui/components/gradient_stops.py" line="126"/>
        <source>Custom</source>
        <extracomment>控件总高度（上下两排标签 + 节点 + 轨道） 轨道高度：刻意比节点直径小，让节点像&quot;卡在细线上的珠子&quot; 左右留白，保证首尾节点的光晕不被裁掉 节点半径（绘制用），直径 12 &gt; 轨道 6 端点菱形的对角半径（菱形长对角线 14） 命中容差（像素） 标签与节点边缘的间隙 相邻标签之间的最小水平间隙，小于它就上下错开 锚点之间的最小位置差（百分比），同时约束拖动与新增 判定「端点」的位置容差（百分比） 调色板预设色（按暖 → 冷排列，覆盖常见压力语义）</extracomment>
        <translation>自定义</translation>
    </message>
    <message>
        <location filename="../../gui/components/gradient_stops.py" line="131"/>
        <source>Delete</source>
        <translation>删除</translation>
    </message>
    <message>
        <location filename="../../gui/components/gradient_stops.py" line="186"/>
        <source>Color</source>
        <translation>颜色</translation>
    </message>
</context>
</TS>
