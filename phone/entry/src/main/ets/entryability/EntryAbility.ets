import { AbilityConstant, UIAbility, Want } from '@kit.AbilityKit';
import { hilog } from '@kit.PerformanceAnalysisKit';
import { window } from '@kit.ArkUI';
import { workScheduler } from '@kit.BackgroundTasksKit';
import { WeWorldVectors } from '../world/WeWorldVectors';
import WeWorkSchedulerAbility from '../proactive/WeWorkSchedulerAbility';
import { WeProactiveBootstrap } from '../ports/WeProactiveBootstrap';

export default class EntryAbility extends UIAbility {
  onCreate(want: Want, launchParam: AbilityConstant.LaunchParam): void {
    // 1) 自检：跑移植验收向量（Python 引擎与 ArkTS 必须同答案）
    WeWorldVectors.selfTest();

    // 2) 接线：把你这边的同步层 / 聊天库 / LLM 客户端交给本包。
    //    示例用 Sample* 三个类；换成你的实现即可。
    WeProactiveBootstrap.setup(
      WeProactiveBootstrap.sampleSnapshotSource(),
      WeProactiveBootstrap.sampleChatSink(),
      WeProactiveBootstrap.sampleLlmClient()
    );

    // 3) 注册唤醒式主动（WorkScheduler）：系统择机唤醒，时机由系统决定
    try {
      const work: workScheduler.WorkInfo = {
        workId: WeWorkSchedulerAbility.WORK_ID,
        bundleName: 'com.example.worldengine',
        abilityName: 'WeWorkSchedulerAbility',
        isRepeat: true,
        isPersisted: true,
        repeatCycleTime: WeWorkSchedulerAbility.REPEAT_MS
      };
      workScheduler.startWork(work);
    } catch (err) {
      hilog.error(0x0926, 'WorldEngine', 'startWork failed: %{public}s', JSON.stringify(err));
    }
  }

  onWindowStageCreate(windowStage: window.WindowStage): void {
    windowStage.loadContent('pages/Index', (err) => {
      if (err.code) {
        hilog.error(0x0926, 'WorldEngine', 'loadContent failed: %{public}s', JSON.stringify(err));
      }
    });
  }
}
