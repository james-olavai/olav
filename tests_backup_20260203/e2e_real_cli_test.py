#!/usr/bin/env python3
"""
OLAV Real E2E CLI Test - 真实的端到端CLI测试

使用 subprocess + echo 模拟真实用户交互，不绕过任何层级

测试方法:
- echo "query" | uv run olav  (模拟用户输入)
- 捕获完整stdout/stderr输出
- 验证实际用户体验
- 使用真实LLM和设备数据

运行方式:
    uv run python tests/e2e_real_cli_test.py
"""

import re
import subprocess
import time
from datetime import datetime
from pathlib import Path


class RealE2ETest:
    """真实的端到端CLI测试 - 无作弊"""

    def __init__(self):
        self.results = {
            "test_date": datetime.now().isoformat(),
            "tests": [],
            "issues": [],
        }
        self.project_root = Path.cwd()

    def run_cli_command(self, query: str, timeout: int = 60) -> dict:
        """运行真实的CLI命令，捕获输出
        
        Args:
            query: 用户查询 (模拟用户输入)
            timeout: 超时时间(秒)
            
        Returns:
            {
                "stdout": str,  # 标准输出
                "stderr": str,  # 错误输出
                "returncode": int,  # 返回码
                "duration": float,  # 执行时间
            }
        """
        print(f"📝 模拟用户输入: {query}")
        
        start = time.time()
        
        try:
            # 使用 echo 管道模拟用户输入
            cmd = f'echo "{query}" | uv run olav'
            
            result = subprocess.run(
                cmd,
                shell=True,
                cwd=self.project_root,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
            
            duration = time.time() - start
            
            return {
                "stdout": result.stdout,
                "stderr": result.stderr,
                "returncode": result.returncode,
                "duration": duration,
            }
            
        except subprocess.TimeoutExpired:
            duration = time.time() - start
            return {
                "stdout": "",
                "stderr": f"Timeout after {timeout}s",
                "returncode": -1,
                "duration": duration,
            }
        except Exception as e:
            duration = time.time() - start
            return {
                "stdout": "",
                "stderr": str(e),
                "returncode": -1,
                "duration": duration,
            }

    def add_result(self, name: str, passed: bool, message: str = ""):
        """记录测试结果"""
        self.results["tests"].append({
            "name": name,
            "passed": passed,
            "message": message,
        })
        status = "✅ PASS" if passed else "❌ FAIL"
        print(f"{status}: {name}")
        if message:
            print(f"   {message}")

    def add_issue(self, severity: str, title: str, detail: str = ""):
        """记录问题"""
        self.results["issues"].append({
            "severity": severity,
            "title": title,
            "detail": detail,
        })
        print(f"⚠️  [{severity}] {title}")
        if detail:
            print(f"   {detail}")

    def test_1_cli_starts_successfully(self):
        """测试1: CLI能否正常启动"""
        print("\n" + "=" * 70)
        print("🚀 测试1: CLI启动检查")
        print("=" * 70)
        
        # 使用 /help 命令测试启动
        result = self.run_cli_command("/help", timeout=10)
        
        # 检查是否成功启动
        success_indicators = [
            "OLAV" in result["stdout"],
            result["returncode"] == 0,
            "ERROR" not in result["stderr"],
            "Traceback" not in result["stderr"],
        ]
        
        passed = all(success_indicators)
        
        if not passed:
            self.add_issue(
                "CRITICAL",
                "CLI启动失败",
                f"stdout: {result['stdout'][:200]}\nstderr: {result['stderr'][:200]}"
            )
        
        self.add_result(
            "CLI启动",
            passed,
            f"耗时: {result['duration']:.2f}s"
        )
        
        return passed

    def test_2_simple_device_query(self):
        """测试2: 简单设备查询 (不需要学习)"""
        print("\n" + "=" * 70)
        print("🔍 测试2: 简单设备查询 (显示所有设备)")
        print("=" * 70)
        
        # 这个查询应该不需要任何学习，直接返回设备列表
        result = self.run_cli_command("显示所有设备", timeout=20)
        
        # 检查输出
        checks = {
            "包含设备名": any(dev in result["stdout"] for dev in ["R1", "R2", "R3", "R4", "SW1", "SW2"]),
            "无严重错误": "ERROR" not in result["stderr"] and "CRITICAL" not in result["stderr"],
            "正常返回": result["returncode"] == 0,
            "响应时间<15s": result["duration"] < 15,
        }
        
        passed = all(checks.values())
        
        if not passed:
            failed_checks = [k for k, v in checks.items() if not v]
            self.add_issue(
                "HIGH",
                "简单查询失败",
                f"失败检查: {failed_checks}\nstdout: {result['stdout'][:500]}"
            )
        
        self.add_result(
            "简单设备查询",
            passed,
            f"耗时: {result['duration']:.2f}s, 通过检查: {sum(checks.values())}/{len(checks)}"
        )
        
        return passed

    def test_3_device_with_learning(self):
        """测试3: 需要学习的设备查询
        
        注意: 由于CLI需要交互式输入学习内容，这个测试会失败
        这是预期行为 - 暴露了真实的用户体验问题
        """
        print("\n" + "=" * 70)
        print("🎓 测试3: 需要学习的查询 (list all ip on R1)")
        print("=" * 70)
        
        result = self.run_cli_command("list all ip addresses on R1", timeout=15)
        
        # 检查是否触发了学习机制
        learning_triggered = any([
            "Learning" in result["stdout"],
            "don't know" in result["stdout"],
            "Which devices" in result["stdout"],
        ])
        
        # 检查是否有实际结果 (如果R1已经被学习过)
        has_result = any([
            "interface" in result["stdout"].lower(),
            "ip address" in result["stdout"].lower(),
            "IP" in result["stdout"],
        ])
        
        # 这个测试目的是暴露问题，不是通过测试
        if learning_triggered and not has_result:
            self.add_issue(
                "HIGH",
                "CLI需要交互式输入才能继续",
                "用户查询被阻塞，需要手动输入设备映射\n"
                + f"stdout: {result['stdout'][:500]}"
            )
            passed = False
        elif has_result:
            passed = True
        else:
            self.add_issue(
                "MEDIUM",
                "查询既没触发学习也没返回结果",
                f"stdout: {result['stdout'][:500]}"
            )
            passed = False
        
        self.add_result(
            "设备学习查询",
            passed,
            f"学习触发: {learning_triggered}, 有结果: {has_result}"
        )
        
        return passed

    def test_4_routing_performance(self):
        """测试4: 路由性能测试"""
        print("\n" + "=" * 70)
        print("⚡ 测试4: 查询路由性能")
        print("=" * 70)
        
        queries = [
            "显示所有设备",
            "查询设备数量",
            "显示设备列表",
        ]
        
        durations = []
        
        for query in queries:
            result = self.run_cli_command(query, timeout=20)
            durations.append(result["duration"])
            print(f"   📊 '{query}': {result['duration']:.2f}s")
        
        avg_duration = sum(durations) / len(durations)
        
        # 性能目标: 平均响应时间 < 12s (考虑到CLI启动开销)
        # 注意: 每次查询都是新进程，包含 ~3s 启动时间
        passed = avg_duration < 12.0
        
        if not passed:
            self.add_issue(
                "MEDIUM",
                "查询响应慢",
                f"平均耗时 {avg_duration:.2f}s > 12s"
            )
        
        self.add_result(
            "查询性能",
            passed,
            f"平均耗时: {avg_duration:.2f}s (目标 <12s, 包含CLI启动)"
        )
        
        return passed

    def test_5_error_handling(self):
        """测试5: 错误处理"""
        print("\n" + "=" * 70)
        print("🛡️  测试5: 错误处理能力")
        print("=" * 70)
        
        # 无意义查询
        result = self.run_cli_command("asdfjkl;qwerzxcv", timeout=20)
        
        # 检查是否优雅处理
        graceful_handling = all([
            result["returncode"] == 0,  # 不应该崩溃
            "Traceback" not in result["stderr"],
            "ERROR" not in result["stderr"] or "CRITICAL" not in result["stderr"],
        ])
        
        passed = graceful_handling
        
        if not passed:
            self.add_issue(
                "MEDIUM",
                "错误处理不优雅",
                f"stderr: {result['stderr'][:200]}"
            )
        
        self.add_result(
            "错误处理",
            passed,
            "无效输入处理正常" if passed else "出现异常"
        )
        
        return passed

    def generate_report(self):
        """生成测试报告"""
        print("\n" + "=" * 70)
        print("📊 测试总结")
        print("=" * 70)
        
        total = len(self.results["tests"])
        passed = sum(1 for t in self.results["tests"] if t["passed"])
        failed = total - passed
        
        print(f"✅ 通过: {passed}/{total}")
        print(f"❌ 失败: {failed}/{total}")
        print(f"📈 通过率: {passed/total*100:.1f}%")
        
        if self.results["issues"]:
            print(f"\n⚠️  发现 {len(self.results['issues'])} 个问题:")
            for issue in self.results["issues"]:
                print(f"   [{issue['severity']}] {issue['title']}")
        
        # 写入markdown报告
        report_path = Path("docs/e2e_real_cli_test_results.md")
        report_path.parent.mkdir(parents=True, exist_ok=True)
        
        with open(report_path, "w", encoding="utf-8") as f:
            f.write(f"# OLAV Real E2E CLI Test Results\n\n")
            f.write(f"**测试日期**: {self.results['test_date']}\n\n")
            f.write(f"## 📊 测试总结\n\n")
            f.write(f"- ✅ **通过**: {passed}/{total}\n")
            f.write(f"- ❌ **失败**: {failed}/{total}\n")
            f.write(f"- 📈 **通过率**: {passed/total*100:.1f}%\n\n")
            
            f.write(f"## 📝 测试详情\n\n")
            f.write("| 测试项 | 状态 | 说明 |\n")
            f.write("|--------|------|------|\n")
            
            for test in self.results["tests"]:
                status = "✅" if test["passed"] else "❌"
                f.write(f"| {test['name']} | {status} | {test['message']} |\n")
            
            if self.results["issues"]:
                f.write(f"\n## ⚠️  发现的问题\n\n")
                for issue in self.results["issues"]:
                    f.write(f"### [{issue['severity']}] {issue['title']}\n\n")
                    f.write(f"{issue['detail']}\n\n")
        
        print(f"\n📄 详细报告已保存: {report_path}")

    def run_all_tests(self):
        """运行所有测试"""
        print("=" * 70)
        print("🚀 OLAV Real E2E CLI Test")
        print("   使用真实CLI入口 (echo | uv run olav)")
        print("=" * 70)
        
        # 按顺序运行测试
        self.test_1_cli_starts_successfully()
        self.test_2_simple_device_query()
        self.test_3_device_with_learning()
        self.test_4_routing_performance()
        self.test_5_error_handling()
        
        # 生成报告
        self.generate_report()
        
        # 返回是否所有测试通过
        total = len(self.results["tests"])
        passed = sum(1 for t in self.results["tests"] if t["passed"])
        
        return passed == total


def main():
    """主函数"""
    tester = RealE2ETest()
    success = tester.run_all_tests()
    
    if success:
        print("\n🎉 所有测试通过!")
        return 0
    else:
        print("\n⚠️  部分测试失败，请查看报告")
        return 1


if __name__ == "__main__":
    import sys
    sys.exit(main())
