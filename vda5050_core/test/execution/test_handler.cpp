/*
 * Copyright (C) 2026 ROS-Industrial Consortium Asia Pacific
 * Advanced Remanufacturing and Technology Centre
 * A*STAR Research Entities (Co. Registration No. 199702110H)
 *
 * Licensed under the Apache License, Version 2.0 (the "License");
 * you may not use this file except in compliance with the License.
 * You may obtain a copy of the License at
 *
 *      http://www.apache.org/licenses/LICENSE-2.0
 *
 * Unless required by applicable law or agreed to in writing, software
 * distributed under the License is distributed on an "AS IS" BASIS,
 * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 * See the License for the specific language governing permissions and
 * limitations under the License.
 */

#include <gmock/gmock.h>

#include <atomic>
#include <chrono>
#include <condition_variable>
#include <mutex>
#include <thread>

#include "vda5050_core/execution/base.hpp"
#include "vda5050_core/execution/context_interface.hpp"
#include "vda5050_core/execution/handler.hpp"
#include "vda5050_core/execution/strategy_interface.hpp"

namespace {

using namespace vda5050_core::execution;  // NOLINT

class MockContext : public ContextInterface
{
public:
  std::atomic_int init_calls = 0;

  void init() override
  {
    init_calls++;
  }

  std::shared_ptr<UpdateBase> get_update_raw(
    std::type_index /*type*/) const override
  {
    return nullptr;
  }

  std::shared_ptr<ResourceBase> get_resource_raw(
    std::type_index /*type*/) const override
  {
    return nullptr;
  }
};

class MockStrategy : public StrategyInterface
{
public:
  std::atomic_int init_calls = 0;
  std::atomic_int step_calls = 0;

  void init(std::shared_ptr<ContextInterface> /*context*/) override
  {
    init_calls++;
  }

  void step(std::shared_ptr<ContextInterface> /*context*/) override
  {
    step_calls++;
  }
};

class BlockingMockStrategy : public StrategyInterface
{
public:
  std::atomic_int init_calls = 0;
  std::atomic_int step_calls = 0;
  std::atomic_int concurrent_steps = 0;
  std::atomic_int max_concurrent_steps = 0;

  std::mutex step_mutex;
  std::condition_variable step_cv;
  bool hold_step = false;
  bool step_entered = false;

  void init(std::shared_ptr<ContextInterface> /*context*/) override
  {
    init_calls++;
  }

  void step(std::shared_ptr<ContextInterface> /*context*/) override
  {
    step_calls++;

    const int concurrent = concurrent_steps.fetch_add(1) + 1;
    int observed_max = max_concurrent_steps.load();
    while (concurrent > observed_max &&
           !max_concurrent_steps.compare_exchange_weak(observed_max, concurrent))
    {
    }

    std::unique_lock lock(step_mutex);
    if (!hold_step)
    {
      concurrent_steps.fetch_sub(1);
      return;
    }
    step_entered = true;
    step_cv.notify_all();
    while (hold_step)
    {
      step_cv.wait(lock);
    }

    concurrent_steps.fetch_sub(1);
  }

  void wait_for_step_entry(std::chrono::milliseconds timeout)
  {
    std::unique_lock lock(step_mutex);
    step_cv.wait_for(lock, timeout, [&] { return step_entered; });
  }

  void release_step()
  {
    std::lock_guard lock(step_mutex);
    hold_step = false;
    step_cv.notify_all();
  }
};

}  // namespace

TEST(HandlerTest, SpinOnceRunsStrategy)
{
  auto context = std::make_shared<MockContext>();
  auto strategy = std::make_shared<MockStrategy>();
  std::vector<std::shared_ptr<StrategyInterface>> strategies = {strategy};

  auto handler = Handler::make(context, strategies);
  EXPECT_EQ(strategy->init_calls, 1);
  EXPECT_EQ(context->init_calls, 1);
  EXPECT_EQ(strategy->step_calls, 1);

  handler->spin_once();
  EXPECT_EQ(strategy->step_calls, 2);
}

TEST(HandlerTest, InitAndRemoveStrategies)
{
  auto context = std::make_shared<MockContext>();
  auto strategy_1 = std::make_shared<MockStrategy>();
  auto strategy_2 = std::make_shared<MockStrategy>();
  std::vector<std::shared_ptr<StrategyInterface>> strategies = {
    strategy_1, strategy_2};

  auto handler = Handler::make(context, strategies);
  EXPECT_EQ(strategy_1->init_calls, 1);
  EXPECT_EQ(strategy_2->init_calls, 1);
  EXPECT_EQ(context->init_calls, 1);

  handler->remove_strategy_by_type<MockStrategy>();
  handler->spin_once();

  EXPECT_EQ(strategy_1->step_calls, 1);
  EXPECT_EQ(strategy_2->step_calls, 1);
}

TEST(HandlerTest, AddAndRemoveStrategy)
{
  auto context = std::make_shared<MockContext>();
  auto strategy = std::make_shared<MockStrategy>();

  auto handler = Handler::make(context);

  handler->add_strategy(strategy);
  EXPECT_EQ(strategy->init_calls, 1);

  handler->spin_once();
  EXPECT_EQ(strategy->step_calls, 1);

  handler->remove_strategy(strategy);
  handler->spin_once();
  EXPECT_EQ(strategy->step_calls, 1);
}

TEST(HandlerTest, SpinInThread)
{
  auto context = std::make_shared<MockContext>();
  auto strategy = std::make_shared<MockStrategy>();
  std::vector<std::shared_ptr<StrategyInterface>> strategies = {strategy};

  auto handler = Handler::make(context, strategies);

  std::atomic_bool thread_running = false;
  auto spin_thread = std::thread([&] {
    thread_running = true;
    handler->spin(std::chrono::milliseconds(100));
  });

  while (!thread_running) std::this_thread::yield();

  std::this_thread::sleep_for(std::chrono::milliseconds(20));
  EXPECT_EQ(strategy->step_calls, 1);

  handler->wake();
  std::this_thread::sleep_for(std::chrono::milliseconds(20));
  EXPECT_GE(strategy->step_calls, 2);

  handler->stop();
  handler->wake();
  if (spin_thread.joinable()) spin_thread.join();
}

TEST(HandlerTest, ConcurrentStrategyModification)
{
  auto context = std::make_shared<MockContext>();
  auto handler = Handler::make(context);

  std::atomic_bool keep_running = true;

  auto spin_thread = std::thread([&] {
    while (keep_running) handler->spin_once();
  });

  auto modifying_thread = std::thread([&] {
    for (int i = 0; i < 100; i++)
    {
      auto strategy = std::make_shared<MockStrategy>();
      handler->add_strategy(strategy);
      handler->remove_strategy(strategy);
    }
    keep_running = false;
  });

  modifying_thread.join();
  spin_thread.join();
  SUCCEED();
}

TEST(HandlerTest, SpinAndSpinOnceSimultaneously)
{
  auto context = std::make_shared<MockContext>();
  auto strategy = std::make_shared<BlockingMockStrategy>();
  std::vector<std::shared_ptr<StrategyInterface>> strategies = {strategy};

  auto handler = Handler::make(context, strategies);
  strategy->hold_step = true;
  const int baseline = strategy->step_calls.load();

  auto spin_thread = std::thread([&] {
    handler->spin(std::chrono::milliseconds(100));
  });

  while (!handler->running())
  {
    std::this_thread::yield();
  }

  handler->wake();
  ASSERT_TRUE(strategy->wait_for_step_entry(std::chrono::seconds(2)));

  // Background spin is blocked inside step(); foreground spin_once can overlap.
  auto foreground = std::thread([&] { handler->spin_once(); });
  const auto overlap_deadline =
    std::chrono::steady_clock::now() + std::chrono::seconds(2);
  while (
    strategy->max_concurrent_steps.load() < 2 &&
    std::chrono::steady_clock::now() < overlap_deadline)
  {
    std::this_thread::sleep_for(std::chrono::milliseconds(1));
  }
  EXPECT_GE(strategy->max_concurrent_steps.load(), 2);

  strategy->release_step();
  foreground.join();

  EXPECT_GE(strategy->step_calls.load(), baseline + 2);

  handler->stop();
  handler->wake();
  if (spin_thread.joinable()) spin_thread.join();
}

TEST(HandlerTest, WakeWithContext)
{
  auto context = std::make_shared<MockContext>();
  auto strategy = std::make_shared<MockStrategy>();
  std::vector<std::shared_ptr<StrategyInterface>> strategies = {strategy};

  auto handler = Handler::make(context, strategies);

  std::atomic_bool thread_running = false;
  auto spin_thread = std::thread([&] {
    thread_running = true;
    handler->spin(std::chrono::milliseconds(100));
  });

  while (!thread_running) std::this_thread::yield();

  std::this_thread::sleep_for(std::chrono::milliseconds(20));
  EXPECT_EQ(strategy->step_calls, 1);

  context->notify_on_change();

  std::this_thread::sleep_for(std::chrono::milliseconds(20));
  EXPECT_EQ(strategy->step_calls, 2);

  handler->stop();
  handler->wake();
  if (spin_thread.joinable()) spin_thread.join();
}
