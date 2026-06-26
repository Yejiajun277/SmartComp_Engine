import { useState } from 'react';
import { Form, Input, InputNumber, Switch, Button, Card, message } from 'antd';
import { ThunderboltOutlined } from '@ant-design/icons';
import { evaluateDescription } from '../api/client';
import DescriptionEvaluator from './DescriptionEvaluator';

/**
 * 任务提交表单组件
 *
 * 支持两步提交流程：
 * 1. 用户输入描述 → 评估描述质量
 * 2. 质量足够 → 直接提交；质量不足 → 展示问题面板 → 用户回答后重新评估
 */
export default function TaskForm({ onSubmit, loading }) {
  const [form] = Form.useForm();
  const [step, setStep] = useState('form'); // 'form' | 'evaluating' | 'questions'
  const [evaluating, setEvaluating] = useState(false);
  const [evaluationResult, setEvaluationResult] = useState(null);

  const handleSubmit = async (values) => {
    // 先评估描述质量
    setEvaluating(true);
    try {
      const result = await evaluateDescription(values.productDescription);

      if (result.quality === 'good') {
        // 质量足够，直接提交
        onSubmit(values);
      } else {
        // 质量不足，展示问题面板
        setEvaluationResult(result);
        setStep('questions');
      }
    } catch (err) {
      // 评估失败时降级为直接提交
      console.warn('描述评估失败，直接提交:', err);
      message.warning('描述评估服务暂时不可用，将直接开始分析');
      onSubmit(values);
    } finally {
      setEvaluating(false);
    }
  };

  const handleQuestionsComplete = async (enrichedDescription, answers) => {
    setEvaluating(true);
    try {
      // 从回答中提取产品名称（如果有）
      const productNameAnswer = answers?.find(a => a.field === 'product_name')?.answer;

      if (productNameAnswer) {
        // 用户提供了产品名，用产品名重新评估
        const result = await evaluateDescription(productNameAnswer);

        if (result.quality === 'good') {
          // 产品名验证通过，用产品名提交
          const values = form.getFieldsValue();
          onSubmit({
            ...values,
            productDescription: productNameAnswer,
          });
          return;
        }
      }

      // 没有产品名或验证未通过，用富描述提交
      const values = form.getFieldsValue();
      onSubmit({
        ...values,
        productDescription: enrichedDescription,
      });
    } catch (err) {
      // 重新评估失败，直接用富描述提交
      console.warn('重新评估失败，直接提交:', err);
      const values = form.getFieldsValue();
      onSubmit({
        ...values,
        productDescription: enrichedDescription,
      });
    } finally {
      setEvaluating(false);
    }
  };

  const handleSkip = () => {
    const values = form.getFieldsValue();
    onSubmit(values);
  };

  const handleBack = () => {
    setStep('form');
    setEvaluationResult(null);
  };

  // 问题面板视图
  if (step === 'questions' && evaluationResult) {
    return (
      <DescriptionEvaluator
        questions={evaluationResult.questions}
        missingDimensions={evaluationResult.missing_dimensions}
        qualityScore={evaluationResult.quality_score}
        originalDescription={form.getFieldValue('productDescription')}
        onComplete={handleQuestionsComplete}
        onSkip={handleSkip}
        onBack={handleBack}
        loading={evaluating || loading}
      />
    );
  }

  // 默认表单视图
  return (
    <Card title="提交分析任务" style={{ height: '100%' }}>
      <Form
        form={form}
        layout="vertical"
        onFinish={handleSubmit}
        initialValues={{ maxCompetitors: 5, skipQa: false, useRuleEngine: false, humanReview: false }}
      >
        <Form.Item
          name="productDescription"
          label="产品描述"
          rules={[{ required: true, message: '请输入产品名称或描述' }]}
        >
          <Input
            placeholder="例：飞书、Notion、钉钉"
            size="large"
          />
        </Form.Item>

        <Form.Item name="maxCompetitors" label="竞品数量">
          <InputNumber min={1} max={8} style={{ width: '100%' }} size="large" />
        </Form.Item>

        <Form.Item name="useRuleEngine" label="规则引擎模式（不调 LLM）" valuePropName="checked">
          <Switch />
        </Form.Item>

        <Form.Item name="skipQa" label="跳过质检" valuePropName="checked">
          <Switch />
        </Form.Item>

        <Form.Item name="humanReview" label="人工审核（竞品确认 + 数据审核）" valuePropName="checked">
          <Switch />
        </Form.Item>

        <Form.Item>
          <Button
            type="primary"
            htmlType="submit"
            loading={loading || evaluating}
            icon={<ThunderboltOutlined />}
            size="large"
            block
          >
            {evaluating ? '评估描述质量...' : '开始分析'}
          </Button>
        </Form.Item>
      </Form>
    </Card>
  );
}
